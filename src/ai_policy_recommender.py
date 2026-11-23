"""Select three grounded policy options using the OpenAI Responses API."""

from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path

import requests

from .ai_policy_profile import prepare_region_profile


DEFAULT_MODEL = "gpt-5-mini"
RESPONSES_URL = "https://api.openai.com/v1/responses"
CATALOG_PATH = Path(__file__).with_name("ai_policy_catalog.json")
GENERAL = "general"
FALLBACK_IDS = ("clinic_followup", "telephone_counseling", "medical_referral")
INSTRUCTIONS = (
    "너는 지방자치단체 금연사업 검토를 지원한다. 전달된 JSON은 참고자료다. 쓸 수 있는 정책과 근거 ID는 데이터에 있다. "
    "서로 다른 정책을 정확히 3개 선택하고 추천 순서대로 반환한다. 각 정책의 allowed_evidence_ids 중 하나를 선택한다. "
    "지역의 공식 통계 또는 관련성이 명확한 집계 근거를 우선한다. 비교의 기준과 표본 범위를 구분하고, 비교 차이를 "
    "원인·통계적 유의성·정책 효과로 해석하지 않는다. 집단의 비율, 인구 비중, 환경 지표를 서로 혼동하지 않는다. "
    "근거가 부족하면 general이 허용된 정책을 선택한다. 이 경우 지역 특성에 근거한 추천으로 해석되지 않는다. "
    "사례의 성과와 지표 값은 선택 지역의 성과 예측이 아니다. 지정된 ID와 필드만 반환한다."
)


@lru_cache(maxsize=1)
def load_catalog() -> dict:
    with CATALOG_PATH.open(encoding="utf-8") as file:
        return {row["id"]: row for row in json.load(file)}


def _openai_settings() -> tuple[str | None, str]:
    import streamlit as st
    from streamlit.errors import StreamlitSecretNotFoundError

    try:
        key = st.secrets.get("OPENAI_API_KEY")
        model = st.secrets.get("OPENAI_MODEL")
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        return None, DEFAULT_MODEL
    return (key if isinstance(key, str) else None,
            model.strip() if isinstance(model, str) and model.strip() else DEFAULT_MODEL)


def _eligible_policies(catalog: dict, facts: dict) -> dict:
    eligible = {}
    for policy_id, policy in catalog.items():
        evidence_ids = [key for key, fact in facts.items() if fact["kind"] in policy["connections"]]
        if policy["general_reason"]:
            evidence_ids.append(GENERAL)
        if evidence_ids:
            eligible[policy_id] = {**policy, "allowed_evidence_ids": evidence_ids}
    return eligible


def _response_schema(eligible: dict) -> dict:
    evidence_ids = sorted({key for policy in eligible.values() for key in policy["allowed_evidence_ids"]})
    return {
        "type": "object", "additionalProperties": False, "required": ["recommendations"],
        "properties": {
            "recommendations": {
                "type": "array", "minItems": 3, "maxItems": 3,
                "items": {"type": "object", "additionalProperties": False, "required": ["policy_id", "evidence_id"],
                          "properties": {"policy_id": {"type": "string", "enum": list(eligible)},
                                         "evidence_id": {"type": "string", "enum": evidence_ids}}},
            },
        },
    }


def _read_selections(body: dict, eligible: dict) -> list[tuple[str, str]]:
    if body["status"] != "completed":
        raise ValueError("Incomplete Responses API output")
    content = [part for output in body["output"] if output["type"] == "message" for part in output["content"]]
    if any(part["type"] == "refusal" for part in content):
        raise ValueError("Responses API refusal")
    output = "".join(part["text"] for part in content if part["type"] == "output_text")
    parsed = json.loads(output)
    rows = parsed["recommendations"]
    if set(parsed) != {"recommendations"} or not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("Expected exactly three recommendations")
    selections = []
    seen = set()
    for row in rows:
        if set(row) != {"policy_id", "evidence_id"}:
            raise ValueError("Unexpected recommendation fields")
        policy_id, evidence_id = row["policy_id"], row["evidence_id"]
        if policy_id in seen or policy_id not in eligible or evidence_id not in eligible[policy_id]["allowed_evidence_ids"]:
            raise ValueError("Duplicate policy or ungrounded recommendation")
        seen.add(policy_id)
        selections.append((policy_id, evidence_id))
    return selections


def _request(profile: dict, eligible: dict, key: str, model: str) -> list[tuple[str, str]]:
    response = requests.post(
        RESPONSES_URL, headers={"Authorization": f"Bearer {key}"}, timeout=(5, 45),
        json={
            "model": model, "store": False, "max_output_tokens": 2500,
            "instructions": INSTRUCTIONS,
            "input": json.dumps({"region_profile": profile, "policy_candidates": list(eligible.values())},
                                ensure_ascii=False, allow_nan=False),
            "text": {"format": {"type": "json_schema", "name": "smokecontrol_recommendations",
                                "strict": True, "schema": _response_schema(eligible)}},
        },
    )
    response.raise_for_status()
    return _read_selections(response.json(), eligible)


def _connection(fact: dict) -> str:
    unit = fact["unit"]
    difference_unit = "%p" if unit == "%" else f" {unit}"
    unit = unit if unit == "%" else f" {unit}"
    parts = [f"{fact['scope']} · {fact['label']} {fact['value']:.1f}{unit}"]
    for comparison in fact["comparisons"]:
        parts.append(f"{comparison['label']} {comparison['value']:.1f}{unit} "
                     f"(차이 {comparison['difference']:+.1f}{difference_unit})")
    if "sample_size" in fact:
        parts.append(f"선택 지역 응답 {fact['sample_size']:,}명")
    if "note" in fact:
        parts.append(fact["note"])
    return " · ".join(parts)


def _card(policy: dict, fact: dict | None) -> dict:
    return {
        "policy_id": policy["id"], "title": policy["title"], "target": policy["target"], "action": policy["action"],
        "reason": policy["general_reason"] if fact is None else policy["connections"][fact["kind"]],
        "regional_connection": "지역에 공통 적용할 수 있는 정책 후보" if fact is None else _connection(fact),
        "considerations": list(policy["considerations"]), "case": {**policy["case"], "outcomes": list(policy["case"]["outcomes"])},
    }


def _fallback(catalog: dict, notice: str) -> dict:
    return {"source": "fallback", "notice": notice, "recommendations": [_card(catalog[key], None) for key in FALLBACK_IDS]}


def recommend_policies(region_profile: Mapping, *, api_key: str | None = None, model: str | None = None) -> dict:
    """Return three display-ready recommendations from the existing district analysis JSON."""
    profile = prepare_region_profile(region_profile)
    catalog = load_catalog()
    if not profile["facts"]:
        return _fallback(catalog, "선택 지역의 분석 근거가 없어 기본 정책 후보를 표시합니다.")
    if api_key is None:
        api_key, configured_model = _openai_settings()
        model = model or configured_model
    if not isinstance(api_key, str) or not api_key.strip():
        return _fallback(catalog, "Streamlit Secrets의 OPENAI_API_KEY가 없어 기본 정책 후보를 표시합니다.")

    model = model or DEFAULT_MODEL
    facts = {fact["id"]: fact for fact in profile["facts"]}
    eligible = _eligible_policies(catalog, facts)
    try:
        selections = _request(profile, eligible, api_key.strip(), model)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return _fallback(catalog, "AI 응답을 사용할 수 없어 기본 정책 후보를 표시합니다.")
    return {"source": "openai", "model": model,
            "recommendations": [_card(catalog[key], facts.get(evidence_id)) for key, evidence_id in selections]}
