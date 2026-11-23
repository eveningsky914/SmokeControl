"""Standalone Streamlit component for recommendations for a selected district."""

from collections.abc import Mapping

import streamlit as st

from .ai_policy_profile import prepare_region_profile
from .ai_policy_recommender import recommend_policies
from .smoking_comparison import METRICS


def _render_card(policy: dict) -> None:
    with st.container(border=True):
        st.subheader(policy["title"])
        st.write("**대상 집단**", policy["target"])
        st.write("**추천 이유**", policy["reason"])
        st.write("**지역 근거**", policy["regional_connection"])
        st.write("**실행안**", policy["action"])
        st.markdown("**시행 시 고려사항**\n\n" + "\n".join(f"- {item}" for item in policy["considerations"]))

        case = policy["case"]
        with st.expander("참고 사례와 출처"):
            st.write("**시행기관**", case["institution"])
            st.write("**사업 대상**", case["target"])
            st.write(case["description"])
            for outcome in case["outcomes"]:
                st.write(outcome)
            if not case["outcomes"]:
                st.caption("인용한 자료에 공개된 성과 수치가 없습니다.")
            st.markdown(f"[{case['title']}]({case['url']})")


def render_ai_policy_recommendations(region_profile: Mapping, *, key: str = "ai_policies") -> None:
    """Render recommendations on demand for the current region analysis."""
    try:
        profile = prepare_region_profile(region_profile)
    except ValueError as error:
        st.warning(str(error))
        return

    region = profile["region"]
    st.title(f"{region['name']} 금연정책 추천")
    st.caption(" · ".join(part for part in (region["province"], f"{profile['year']}년 지역사회건강조사") if part))
    label = METRICS[profile["metric"]]
    if profile["official_rate"] is None:
        st.caption(f"{label} 공식 통계를 확인할 수 없습니다.")
    else:
        district, national = st.columns(2)
        district.metric(f"{label} · {profile['official_rate_type']}", f"{profile['official_rate']:.1f}%")
        benchmarks = next((fact["comparisons"] for fact in profile["facts"]
                           if fact["kind"] == "smoking_rate" and fact["comparisons"]), [])
        for comparison in benchmarks:
            if comparison["label"] == "전국 시·군·구 중앙값":
                national.metric(comparison["label"], f"{comparison['value']:.1f}%",
                                help=f"선택 지역과의 차이 {comparison['difference']:+.1f}%p")
                break

    result_key = f"{key}_result"
    if result_key in st.session_state and st.session_state[result_key][0] != profile:
        del st.session_state[result_key]
    if st.button("AI 정책 추천", type="primary", key=f"{key}_button"):
        with st.spinner("지역 분석을 바탕으로 정책을 검토하고 있습니다."):
            st.session_state[result_key] = (profile, recommend_policies(region_profile))
    if result_key not in st.session_state:
        return

    _, result = st.session_state[result_key]
    if result["source"] == "fallback":
        st.info(result["notice"])
    for policy in result["recommendations"]:
        _render_card(policy)
