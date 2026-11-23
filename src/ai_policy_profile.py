"""Select policy evidence from the existing district-level analysis artifact."""

from collections.abc import Mapping
from functools import lru_cache
import json
from math import isfinite
from numbers import Real
from pathlib import Path

from .data_loader import ROOT
from .smoking_comparison import AGE_BANDS, METRICS, MIN_CELL_COUNT
from .smoking_inputs import FACTORS as REGIONAL_FACTORS
from .smoking_survey import FACTORS as SURVEY_FACTORS, SUMMARY_PATH


ARTIFACT = ROOT / "data" / "processed" / SUMMARY_PATH
SURVEY_KINDS = {
    "sex": "sex", "age_band": "age", "work": "employment", "occupation": "occupation",
    "income": "income", "assistance": "assistance", "drinking": "drinking", "high_risk": "drinking",
    "stress": "stress", "depression": "mood",
}
REGIONAL_KINDS = {
    "low_income": "vulnerability", "employment": "employment", "unemployment": "employment",
    "doctors": "health_access", "manufacturing": "manufacturing", "parks": "environment",
    "high_risk_drinking": "drinking", "stress": "stress", "depression": "mood",
    "older": "population_age", "retail": "retail_density",
}


@lru_cache(maxsize=1)
def _read_artifact(path: Path, modified_ns: int) -> dict:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise ValueError("지원되는 지역 흡연 분석 자료 버전을 찾지 못했습니다.")
    return data


def build_region_profile(code: str, province: str, name: str, year: int, metric: str = "tobacco",
                         *, artifact_path: Path = ARTIFACT) -> dict:
    """Read one district and metric without substituting a different analysis year."""
    artifact_path = Path(artifact_path)
    data = _read_artifact(artifact_path, artifact_path.stat().st_mtime_ns)
    code = str(code)
    year_key = str(year)
    report = data["results"].get(metric, {}).get(year_key)
    if report is None:
        raise ValueError("선택한 연도와 지표의 분석 결과가 없습니다.")

    district_rows = [row for row in report["individual"] if row.get("adm_cd") == code]
    sample_rows = [row for row in report["individual"] if row.get("scope") == "sample"]
    regional = data["regional"].get(metric, {}).get(year_key) or {}
    composition = report["comparison"].get(code, {}).get("national_age")
    return {
        "region": {"code": code, "province": province, "name": name}, "year": year, "metric": metric,
        "official": report["official"].get(code, {}),
        "benchmarks": {"national_median": report["official_national_median"], "province": report["province"].get(province)},
        "composition_reference": "national_age", "composition": composition,
        "individual": {"district_estimates": district_rows, "sample_estimates": sample_rows},
        "regional": {"values": regional.get("districts", {}).get(code, {}), "factors": regional.get("stats", {})},
    }


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _rows(value):
    return value if isinstance(value, (list, tuple)) else ()


def _number(value) -> float | None:
    if isinstance(value, Real) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def _percent(value) -> float | None:
    number = _number(value)
    return number if number is not None and 0 <= number <= 100 else None


def prepare_region_profile(region_profile: Mapping) -> dict:
    """Whitelist aggregated, verifiable fields from a selected district JSON export."""
    region_profile = _mapping(region_profile)
    region = _mapping(region_profile.get("region"))
    code, province, name = (str(region.get(key) or "").strip() for key in ("code", "province", "name"))
    year, metric = region_profile.get("year"), region_profile.get("metric")
    if not (code and name and type(year) is int and isinstance(metric, str) and metric in METRICS):
        raise ValueError("지역 코드·이름, 분석 연도, 흡연 지표가 들어 있는 지역 분석 JSON이 필요합니다.")

    facts = []

    def add(kind, label, scope, value, unit="%", *, comparisons=(), sample_size=None, note=None):
        if value is None:
            return
        fact = {"id": f"e{len(facts) + 1}", "kind": kind, "label": label, "scope": scope, "value": value, "unit": unit}
        fact["comparisons"] = [{"label": name, "value": number, "difference": value - number}
                               for name, number in comparisons if number is not None]
        if sample_size is not None:
            fact["sample_size"] = int(sample_size)
        if note:
            fact["note"] = note
        facts.append(fact)

    official = _mapping(region_profile.get("official"))
    benchmarks = _mapping(region_profile.get("benchmarks"))
    standard = _percent(official.get("std")) if not official.get("std_flag") else None
    crude = _percent(official.get("crude")) if not official.get("flag") else None
    add("smoking_rate", f"{METRICS[metric]} 표준화율", "선택 지역 공식 통계", standard,
        comparisons=[("전국 시·군·구 중앙값", _percent(benchmarks.get("national_median"))),
                     ("소속 시·도 표준화율", _percent(benchmarks.get("province")))])
    add("smoking_rate", f"{METRICS[metric]} 조율", "선택 지역 공식 통계", crude)

    composition = _mapping(region_profile.get("composition"))
    reference = region_profile.get("composition_reference")
    if reference in ("national_age", "sample_sex_age"):
        label = "전국 연령별 기준" if reference == "national_age" else "제공 표본 성별·연령별 기준"
        add("composition", f"인구구성 기반 기대 조율 ({label})", "선택 지역 모형 기대값",
            _percent(composition.get("expected")), comparisons=[("같은 지역의 실제 조율", crude)],
            note="인구구성 비교로, 정책 효과 추정치는 아님")

    individual = _mapping(region_profile.get("individual"))
    sample = {(row.get("factor"), row.get("category")): _percent(row.get("rate"))
              for row in _rows(individual.get("sample_estimates"))
              if isinstance(row, Mapping) and row.get("scope") == "sample"
              and isinstance(row.get("factor"), str) and isinstance(row.get("category"), str)
              and (_number(row.get("n")) or 0) >= MIN_CELL_COUNT}
    for row in _rows(individual.get("district_estimates")):
        if not isinstance(row, Mapping) or str(row.get("adm_cd")) != code or row.get("scope") != "district":
            continue
        factor, category = row.get("factor"), row.get("category")
        size = _number(row.get("n")) or 0
        if not isinstance(factor, str) or factor not in SURVEY_KINDS or size < MIN_CELL_COUNT:
            continue
        if not isinstance(category, str) or not category.strip():
            continue
        kind = SURVEY_KINDS[factor]
        if factor == "age_band" and category == AGE_BANDS[0]:
            kind = "young_adult"
        elif factor == "income" and category == "200만 원 미만":
            kind = "lower_income"
        elif factor == "assistance" and category == "현재 수급":
            kind = "vulnerability"
        add(kind, f"{SURVEY_FACTORS[factor]} · {category}의 {METRICS[metric]}",
            "선택 지역 가중 표본", _percent(row.get("rate")),
            comparisons=[("같은 집단의 제공 표본 가중 추정치", sample.get((factor, category)))], sample_size=size)

    regional = _mapping(region_profile.get("regional"))
    values, stats = (_mapping(regional.get(key)) for key in ("values", "factors"))
    for factor, kind in REGIONAL_KINDS.items():
        if factor not in values:
            continue
        label, unit, _ = REGIONAL_FACTORS[factor]
        read_value = _percent if unit == "%" else _number
        median = read_value(_mapping(stats.get(factor)).get("median"))
        add(kind, label, "선택 지역 환경 지표", read_value(values[factor]), unit,
            comparisons=[("비교 지역 중앙값", median)],
            note="인허가 스냅샷 기반 탐색 지표" if factor == "retail" else None)

    return {"region": {"code": code, "province": province, "name": name}, "year": year,
            "metric": metric, "official_rate": standard if standard is not None else crude,
            "official_rate_type": "표준화율" if standard is not None else "조율", "facts": facts}
