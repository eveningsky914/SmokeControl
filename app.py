import streamlit as st
from shapely.geometry import Point, shape
from streamlit_folium import st_folium

from src.data_loader import available_years, load_boundaries, load_rates, load_sido_boundaries
from src.analysis import build_seoul_analysis, load_active_retailer_counts, load_seoul_health_indicators, load_seoul_population
from src.map_view import build_map
from src.policy_recommender import PolicyContext
from src.policy_view import render_policy_report
from src.region_utils import PROVINCES


st.set_page_config(page_title="SmokeControl | 지역 흡연 현황", page_icon="S", layout="wide")

st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;600;700&display=swap');
      :root { --ink:#17191f; --muted:#6b7280; --line:#e9eaee; --blue:#4f6ef7; --surface:#f6f7f9; }
      html, body, [class*="css"] { font-family: Inter, 'Noto Sans KR', sans-serif; color:var(--ink); }
      .stApp { background:#fff; }
      [data-testid="stAppViewContainer"] { background:#fff; }
      [data-testid="stSidebar"] { background:#f8f9fb; border-right:1px solid var(--line); }
      [data-testid="stSidebar"] > div:first-child { padding-top:1.1rem; }
      [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color:#596273; }
      .block-container { max-width:1600px; padding:2rem 2.4rem 3rem; }
      h1,h2,h3 { letter-spacing:-.035em; color:var(--ink); }
      h1 { font-size:2rem !important; font-weight:700 !important; }
      h2 { font-size:1.25rem !important; font-weight:650 !important; }
      .brand { font-size:1.25rem; font-weight:700; letter-spacing:-.04em; color:#17191f; }
      .brand-mark { display:inline-flex; width:30px; height:30px; border-radius:9px; background:#4f6ef7; color:white; align-items:center; justify-content:center; margin-right:8px; font-size:15px; }
      .eyebrow { color:#7a8190; font-size:.75rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase; }
      .page-subtitle { color:#6b7280; font-size:.96rem; margin-top:-.55rem; }
      .kpi-card { border:1px solid #e9eaee; background:#fff; border-radius:12px; padding:17px 18px 14px; min-height:117px; }
      .kpi-label { color:#6b7280; font-size:.83rem; font-weight:500; margin-bottom:12px; }
      .kpi-value { color:#17191f; font-size:1.7rem; line-height:1.15; font-weight:650; letter-spacing:-.04em; }
      .kpi-note { color:#8a909d; font-size:.76rem; margin-top:8px; }
      .panel { border:1px solid #e9eaee; background:white; border-radius:12px; padding:17px 18px; }
      .section-label { color:#6b7280; font-size:.78rem; font-weight:600; margin-bottom:4px; }
      .region-title { font-size:1.1rem; font-weight:650; color:#17191f; }
      div[data-testid="stSelectbox"] label { font-weight:600; color:#4b5563; }
      div[data-testid="stSelectbox"] [data-baseweb="select"] > div { border-radius:9px; border-color:#e2e5eb; }
      .stButton button[kind="primary"] { background:#4f6ef7; border-color:#4f6ef7; border-radius:9px; font-weight:600; }
      .stButton button { border-radius:9px; }
      [data-testid="stMetric"] { border:1px solid #e9eaee; border-radius:12px; padding:15px 17px; background:#fff; }
      [data-testid="stMetricLabel"] { color:#6b7280; }
      [data-testid="stMetricValue"] { color:#17191f; font-size:1.65rem; }
      hr { border-color:#e9eaee; }
      @media (max-width:900px) { .block-container { padding:1.2rem 1rem 2rem; } }
    </style>
    """,
    unsafe_allow_html=True,
)


def show_metric(label, value, note):
    rendered = "데이터 없음" if value is None else f"{value:.1f}%"
    st.markdown(
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{rendered}</div><div class="kpi-note">{note}</div></div>',
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner="서울 분석자료를 불러오는 중입니다…")
def load_analysis_inputs():
    return load_seoul_health_indicators(), load_active_retailer_counts(), load_seoul_population()


rates = load_rates()
geo = load_boundaries()
sido_geo = load_sido_boundaries()
years = available_years(rates)
if not years:
    years = [2025]

pending_province = st.session_state.pop("pending_province", None)
if pending_province in PROVINCES:
    st.session_state["province"] = pending_province
    st.session_state.pop("selected_region", None)

saved_filters = st.session_state.pop("restore_map_filters", None)
if saved_filters:
    st.session_state["province"], st.session_state["year"] = saved_filters


def reset_region():
    st.session_state.pop("selected_region", None)
    st.session_state.pop("processed_map_click", None)


page = st.session_state.get("page", "dashboard")
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">S</span>SmokeControl</div>', unsafe_allow_html=True)
    st.caption("지역 건강정책 데이터 워크스페이스")
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='eyebrow'>WORKSPACE</div>", unsafe_allow_html=True)
    st.markdown("**●  대시보드**" if page == "dashboard" else "대시보드")
    st.markdown("지역별 흡연율")
    st.markdown("**●  관련 요인 분석**" if page == "analysis" else "관련 요인 분석")
    st.markdown("**●  금연정책 추천**" if page == "policies" else "금연정책 추천")
    st.markdown("<div style='height:34px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='eyebrow'>ABOUT</div>", unsafe_allow_html=True)
    st.markdown("[데이터 출처](DATA_SOURCES.txt)")
    st.caption("SmokeControl MVP · 지역사회건강조사")


if page in {"analysis", "policies"} and st.session_state.get("selected_region"):
    code = str(st.session_state.selected_region)
    if page == "policies":
        if st.button("← 지역 분석으로 돌아가기"):
            st.session_state.page = "analysis"
            st.rerun()
    elif st.button("← 지도 대시보드로 돌아가기"):
        st.session_state.page = "dashboard"
        st.session_state.restore_map_filters = st.session_state.pop("analysis_map_filters", None)
        st.rerun()

    try:
        health, retailers, population = load_analysis_inputs()
        analysis = build_seoul_analysis(rates, health, retailers, population, code, year=2025)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        st.error(f"분석에 필요한 자료를 불러오지 못했습니다: {exc}")
        st.stop()

    if page == "policies":
        render_policy_report(PolicyContext.from_analysis(analysis))
        st.stop()

    st.markdown('<div class="eyebrow">SEOUL DISTRICT ANALYSIS · 2025</div>', unsafe_allow_html=True)
    st.title("서울 자치구 흡연율 분석")
    st.markdown('<p class="page-subtitle">현재 보유한 2025년 지표로 선택 자치구와 서울 25개 구를 비교합니다.</p>', unsafe_allow_html=True)
    st.info("이 화면은 서울 자치구 간 관측된 연관성을 탐색합니다. 지역 단위 비교이며 개인의 흡연 원인이나 인과관계를 증명하지 않습니다.")
    kpis = st.columns(3, gap="medium")
    with kpis[0]:
        show_metric(f"{analysis['district']} 담배제품 현재사용률", analysis["rate"], "2025년 공식 표준화율")
    with kpis[1]:
        show_metric("서울 자치구 중앙값", analysis["peer_median"], f"서울 {analysis['district_count']}개 구의 중앙값")
    with kpis[2]:
        st.metric("서울 내 사용률 순위", f"{analysis['rank']} / {analysis['district_count']}", "높은 순")

    st.markdown("### 서울 안에서의 위치")
    direction = "높습니다" if analysis["difference"] > 0 else "낮습니다" if analysis["difference"] < 0 else "같습니다"
    st.write(
        f"**{analysis['district']}**의 2025년 담배제품 현재사용률은 **{analysis['rate']:.1f}%**로, "
        f"서울 자치구 중앙값({analysis['peer_median']:.1f}%)보다 "
        f"**{abs(analysis['difference']):.1f}%p {direction}**. 서울 구별 분포에서는 **{analysis['band']}**입니다."
    )
    st.caption("구간은 서울 자치구 분포의 1·3사분위수로 나눈 비교용 구간입니다. 다른 시·도와의 등급 비교에는 사용하지 않습니다.")

    st.markdown("### 함께 살펴볼 수 있는 지표")
    st.caption("각 행은 선택 구와 서울 구 중앙값의 차이를 보여줍니다. Spearman ρ는 서울 구 25곳에서의 단조 연관성 탐색값입니다.")
    factors = analysis["factors"].copy()
    if not factors.empty:
        display = factors[["변수", "단위", "선택 지역", "서울 구 중앙값", "서울 중앙값과 차이", "흡연율과의 Spearman ρ", "비교 구 수"]].copy()
        st.dataframe(
            display,
            width="stretch",
            hide_index=True,
            column_config={
                "선택 지역": st.column_config.NumberColumn(format="%.1f"),
                "서울 구 중앙값": st.column_config.NumberColumn(format="%.1f"),
                "서울 중앙값과 차이": st.column_config.NumberColumn(format="%+.1f"),
                "흡연율과의 Spearman ρ": st.column_config.NumberColumn(format="%+.2f"),
            },
        )
        candidates = factors[factors["비교 구 수"] >= 20].dropna(subset=["흡연율과의 Spearman ρ"])
        notable = candidates[candidates["흡연율과의 Spearman ρ"].abs() >= 0.3].head(3)
        if notable.empty:
            st.caption("현재 자료에서 상대적으로 뚜렷한 구 단위 연관성 신호(|ρ| ≥ 0.30)는 확인되지 않았습니다.")
        else:
            with st.expander("서울 구 간 연관성 신호 해석", expanded=True):
                for _, row in notable.iterrows():
                    rho = row["흡연율과의 Spearman ρ"]
                    value = row["선택 지역"]
                    median = row["서울 구 중앙값"]
                    factor_name = row["변수"]
                    relation = "높은 구일수록 사용률도 높은 경향" if rho > 0 else "높은 구일수록 사용률은 낮은 경향"
                    position = "서울 구 중앙값보다 높음" if value > median else "서울 구 중앙값보다 낮음" if value < median else "서울 구 중앙값과 같음"
                    st.write(f"- **{factor_name}**: {analysis['district']}은 {position}; 서울 구 비교에서 {relation} (ρ={rho:+.2f}). 연관 신호이며 원인으로 해석할 수 없습니다.")

        label_to_column = {
            "담배소매점(인구 1만 명당)": "retailers_per_10k",
            **{name: name for name in factors["변수"] if name != "담배소매점(인구 1만 명당)"},
        }
        labels = list(label_to_column)
        chosen_factor = st.selectbox("서울 자치구 분포에서 변수 살펴보기", labels)
        x_column = label_to_column[chosen_factor]
        chart = analysis["peer_data"][["sigungu", "rate", x_column]].dropna().rename(columns={"sigungu": "자치구", x_column: chosen_factor})
        st.scatter_chart(chart, x=chosen_factor, y="rate", height=340, width="stretch")
        st.caption(f"점 하나가 서울 자치구 하나입니다. 선택 구: {analysis['district']} · 세로축: 담배제품 현재사용률(%) · 가로축: {chosen_factor}")
    else:
        st.warning("선택 지역에서 비교 가능한 분석 변수를 찾지 못했습니다.")

    st.markdown("### 해석 범위와 데이터 기준")
    st.markdown(
        "- 흡연 결과: 질병관리청 2025년 담배제품 현재사용률 **표준화율**\n"
        "- 건강행태 비교: 같은 통계집의 2025년 시·군·구 표준화 추정치, 서울 25개 구\n"
        "- 담배소매점: 현재 정상 영업으로 표기된 점포 주소를 구별 집계하고, SGIS 2024년 총인구로 1만 명당 수를 계산\n"
        "- 판매점 수는 과거 연도 자료가 아닌 현재 파일 기준이며, 접근성의 거친 대리변수입니다. 경계 거리·인과 효과를 측정하지 않습니다.\n"
        "- 이 자료에는 개인별 원시 응답, 소득, 교육수준이 포함되어 있지 않아 해당 요인은 분석하지 않습니다."
    )
    if st.button("금연정책 추천 보기", type="primary", key="open_policy_report"):
        st.session_state.page = "policies"
        st.rerun()
    st.stop()


st.markdown('<div class="eyebrow">SMOKING MONITOR</div>', unsafe_allow_html=True)
st.title("지역 흡연 현황")
st.markdown('<p class="page-subtitle">지역별 담배제품 현재사용 현황과 행정구역별 분포를 탐색하세요.</p>', unsafe_allow_html=True)

filter_cols = st.columns([2.2, 1, 3.8], gap="medium")
with filter_cols[0]:
    province = st.selectbox("지역", PROVINCES, key="province", on_change=reset_region)
with filter_cols[1]:
    if st.session_state.get("year") not in years:
        st.session_state["year"] = 2025 if 2025 in years else years[-1]
    year = st.selectbox("기준연도", years, key="year")
with filter_cols[2]:
    st.markdown("<div style='height:29px'></div>", unsafe_allow_html=True)
    st.caption("지표: 담배제품 현재사용률 · 공식 표준화율 기준")

current = rates[rates.year == year] if not rates.empty else rates
national = current[current.level == "national_median"] if not current.empty and "level" in current else current.iloc[0:0]
province_rows = current[(current.level == "sido") & (current.sido == province)] if not current.empty and province != "전국" else current.iloc[0:0]
selected_code = st.session_state.get("selected_region")
selected = current[current.adm_cd.astype(str) == str(selected_code)] if selected_code and not current.empty else current.iloc[0:0]
national_value = float(national.rate.iloc[0]) if not national.empty else None
province_value = float(province_rows.rate.iloc[0]) if not province_rows.empty else None
selected_value = float(selected.rate.iloc[0]) if not selected.empty else None
difference = province_value - national_value if province_value is not None and national_value is not None else None

kpi_cols = st.columns(3, gap="medium")
with kpi_cols[0]:
    show_metric("전국 시·군·구 중앙값", national_value, f"{year}년 · 전국 성인 평균이 아닌 시·군·구 중앙값")
with kpi_cols[1]:
    show_metric(f"{province} 담배제품 현재사용률" if province != "전국" else "시·도 담배제품 현재사용률", province_value, f"{year}년 · 공식 시·도 표준화율")
with kpi_cols[2]:
    show_metric("전국 중앙값 대비", difference, "선택 시·도 값에서 전국 시·군·구 중앙값을 뺀 값")

st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
map_col, detail_col = st.columns([2.35, 1], gap="medium")
with map_col:
    st.markdown(f'<div class="section-label">INTERACTIVE MAP · {year}</div><div class="region-title">{province} 지역별 분포</div>', unsafe_allow_html=True)
    fmap = build_map(geo, rates, year, province, selected_code, sido_geo=sido_geo)
    result = st_folium(fmap, height=690, use_container_width=True, returned_objects=["last_clicked"])
    click = result.get("last_clicked") if result else None
    click_geo = sido_geo if province == "전국" else geo
    if click and click != st.session_state.get("processed_map_click") and click_geo.get("features"):
        st.session_state.processed_map_click = click
        point = Point(click["lng"], click["lat"])
        for feature in click_geo["features"]:
            props = feature.get("properties", {})
            code = props.get("adm_cd") or props.get("SIG_CD") or props.get("SIGUNGU_CD") or props.get("sigungu_code")
            try:
                if code and shape(feature["geometry"]).contains(point):
                    if province == "전국":
                        st.session_state.pending_province = props.get("sido") or props.get("SIDO_NM")
                    else:
                        st.session_state.selected_region = str(code)
                    st.rerun()
            except (KeyError, ValueError, TypeError):
                continue
    st.caption("출처: 질병관리청 지역사회건강조사 · 행정경계: 국가데이터처 SGIS")
    analysis_enabled = province == "서울특별시" and bool(selected_code) and year == 2025
    if st.button("분석하기", type="primary", disabled=not analysis_enabled, use_container_width=True, key="open_seoul_analysis"):
        st.session_state.analysis_map_filters = (province, year)
        st.session_state.page = "analysis"
        st.rerun()
    if province != "서울특별시":
        st.caption("분석하기는 현재 서울특별시 시·군·구만 지원합니다.")
    elif not selected_code:
        st.caption("서울 지도를 클릭해 시·군·구를 선택하면 분석할 수 있습니다.")
    elif year != 2025:
        st.caption("현재 확보된 비교 변수는 2025년 기준입니다. 분석하려면 기준연도를 2025년으로 선택하세요.")

with detail_col:
    with st.container(border=True):
        st.markdown('<div class="section-label">지역 상세</div>', unsafe_allow_html=True)
        if province == "전국":
            st.markdown('<div class="region-title">전국 시·도</div>', unsafe_allow_html=True)
            st.write("지도에서 시·도를 선택하면 해당 지역의 시·군·구 지도로 이동합니다.")
            st.metric("전국 시·군·구 중앙값", "데이터 없음" if national_value is None else f"{national_value:.1f}%")
        else:
            st.markdown(f'<div class="region-title">{province}</div>', unsafe_allow_html=True)
            st.metric("시·도 담배제품 현재사용률", "데이터 없음" if province_value is None else f"{province_value:.1f}%")
            if selected.empty:
                st.caption("지도에서 시·군·구를 선택하세요.")
            else:
                name = selected.sigungu.iloc[0]
                st.markdown("---")
                st.markdown(f"**선택 시·군·구**  \n{name}")
                st.metric("담배제품 현재사용률", f"{selected_value:.1f}%")
                st.caption(f"{year}년 · 공식 표준화율")
        st.markdown("---")
        st.markdown("**지표 안내**")
        st.caption("일반담배 또는 전자담배 등 조사에서 정의한 담배제품을 하나 이상 현재 사용하는 비율입니다. 담배 유형별 사용률을 합산하지 않습니다.")

if not geo.get("features") or not sido_geo.get("features"):
    st.warning("행정경계 GeoJSON을 찾지 못했습니다. data/processed 경계 파일을 확인하세요.")
if rates.empty:
    st.warning("검증된 지역별 통계 파일이 없어 수치를 표시하지 않습니다.")
