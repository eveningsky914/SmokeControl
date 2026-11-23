"""Streamlit entry point for the standalone SmokeControl policy app."""

import streamlit as st

from src.ai_policy_profile import build_region_profile
from src.ai_policy_view import render_ai_policy_recommendations
from src.data_loader import load_rates
from src.region_utils import PROVINCES
from src.smoking_comparison import METRIC_YEARS


POLICY_METRIC = "tobacco"


def main() -> None:
    st.set_page_config(page_title="SmokeControl | 지역 맞춤 금연정책", layout="centered")
    st.caption("SmokeControl")

    try:
        rates = load_rates()
    except (OSError, ValueError):
        st.error("지역 목록을 읽을 수 없습니다. `data/processed/tobacco_rates.csv`를 확인하세요.")
        return
    if rates.empty or "level" not in rates.columns:
        st.error("지역 목록이 없습니다. `data/processed/tobacco_rates.csv`를 확인하세요.")
        return

    districts = rates.loc[
        rates["level"].eq("sigungu") & rates["year"].isin(METRIC_YEARS[POLICY_METRIC]),
        ["sido", "sigungu", "adm_cd", "year"],
    ].dropna()
    available_provinces = set(districts["sido"])
    provinces = [name for name in PROVINCES if name in available_provinces]
    if not provinces:
        st.warning("금연정책을 검토할 수 있는 시·군·구 자료가 없습니다.")
        return

    province_column, district_column, year_column = st.columns([2, 2, 1])
    province = province_column.selectbox("시·도", provinces, key="policy_province")
    province_districts = districts.loc[districts["sido"].eq(province)]
    district_names = sorted(province_districts["sigungu"].unique())
    district = district_column.selectbox("시·군·구", district_names, key="policy_district")
    district_rows = province_districts.loc[province_districts["sigungu"].eq(district)]
    years = sorted(map(int, district_rows["year"].unique()), reverse=True)
    year = year_column.selectbox("기준연도", years, key="policy_year")
    code = district_rows.loc[district_rows["year"].eq(year), "adm_cd"].iloc[0]

    try:
        profile = build_region_profile(code, province, district, year, POLICY_METRIC)
    except FileNotFoundError:
        st.error("지역 분석 결과 파일이 없습니다. `data/processed/national_smoking_analysis.json`을 확인하세요.")
        return
    except (OSError, ValueError, KeyError):
        st.error("선택한 지역과 연도의 분석 결과를 읽을 수 없습니다.")
        return

    render_ai_policy_recommendations(profile)


if __name__ == "__main__":
    main()
