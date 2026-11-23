"""Streamlit report for an already analyzed district."""

import streamlit as st

from .policy_catalog import POLICIES
from .policy_recommender import (
    MIN_COMPARISON_DISTRICTS,
    PRIORITY_GAP_PP,
    PolicyContext,
    PolicyRecommender,
    recommend_policies,
)


PRIORITY_LABELS = {3: "우선 검토", 2: "확대 검토", 1: "기본 지원", 0: "추가 검토"}


def render_policy_report(context: PolicyContext, recommender: PolicyRecommender = recommend_policies) -> None:
    st.title(f"{context.district} 금연정책 추천")
    st.caption(f"서울 자치구 비교 · {context.year}년 지역사회건강조사 · 규칙 기반 추천")

    use = context.tobacco_use
    district_col, median_col, band_col = st.columns(3)
    district_col.metric("담배제품 현재사용률", f"{use.value:.1f}%")
    median_col.metric(f"서울 {use.district_count}개 구 중앙값", f"{use.median:.1f}%")
    band_col.metric("서울 내 분포", context.band.replace("서울 내 ", ""))

    for recommendation in recommender(context):
        policy = POLICIES[recommendation.policy_id]
        with st.container(border=True):
            st.caption(PRIORITY_LABELS[recommendation.priority])
            st.subheader(policy.title)
            st.markdown(f"**지역에서 검토할 이유**　{recommendation.reason}")
            st.markdown(f"**실행안**　{policy.action}")
            st.markdown(f"**성과 지표**　{policy.measure}")
            with st.expander("국내 사례와 연구 근거"):
                st.write(policy.local_example)
                st.markdown(f"[{policy.local_source.title}]({policy.local_source.url})")
                if policy.local_evaluation:
                    st.markdown(f"[{policy.local_evaluation.title}]({policy.local_evaluation.url})")
                st.write(policy.evidence)
                st.markdown(" · ".join(f"[{source.title}]({source.url})" for source in policy.international_sources))

    with st.expander("추천 기준과 데이터 범위"):
        st.write(
            f"비교 가능 지역이 {MIN_COMPARISON_DISTRICTS}개 구 이상일 때 지역 우선순위를 적용합니다. "
            f"금연 시도율이 중앙값보다 {PRIORITY_GAP_PP:g}%p 이상 낮으면 캠페인을, "
            f"직장 실내 간접흡연 노출률이 {PRIORITY_GAP_PP:g}%p 이상 높으면 실내 금연 관리를 우선 검토합니다. "
            "담배제품 현재사용률이 서울 내 높은 구간이고 중앙값을 넘으면 상담 지원 확대를 검토합니다. "
            "이 기준은 사업 검토 순서를 정하기 위한 기준입니다. 효과 크기와 통계적 유의성은 별도 평가가 필요합니다."
        )
        if context.retailers is not None:
            st.write(
                f"소매점은 인구 1만 명당 {context.retailers.value:.1f}개소입니다. "
                f"서울 자치구 중앙값은 {context.retailers.median:.1f}개소입니다. "
                "판매점 현황과 2024년 SGIS 인구를 결합한 참고 지표입니다."
            )
