import streamlit as st
from shapely.geometry import Point, shape
from streamlit_folium import st_folium

from src.ai_policy_profile import build_region_profile
from src.ai_policy_view import render_ai_policy_recommendations
from src.data_loader import ROOT, available_years, load_boundaries, load_rates, load_sido_boundaries
from src.map_view import build_map
from src.region_utils import PROVINCES
from src.smoking_analysis_view import render_analysis
from src.smoking_comparison import METRIC_YEARS


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
      [data-testid="stSidebar"] .stButton button[kind="tertiary"] {
        justify-content:flex-start; min-height:0; padding:0; border:0;
        background:transparent; box-shadow:none; color:var(--ink);
      }
      [data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover,
      [data-testid="stSidebar"] .stButton button[kind="tertiary"]:focus-visible {
        color:var(--blue); text-decoration:underline;
      }
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


def navigate(target_page):
    current_page = st.session_state.get("page", "dashboard")
    if current_page == target_page:
        return
    if current_page == "dashboard":
        st.session_state.analysis_map_filters = (st.session_state.get("province", "전국"),
                                                 st.session_state.get("year", 2025))
    elif target_page == "dashboard":
        filters = st.session_state.pop("analysis_map_filters", None)
        previous_location_filters = st.session_state.pop("location_map_filters", None)
        st.session_state.restore_map_filters = filters or previous_location_filters
    st.session_state.page = target_page


page = st.session_state.get("page", "dashboard")
with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">S</span>SmokeControl</div>', unsafe_allow_html=True)
    st.caption("지역 건강정책 데이터 워크스페이스")
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='eyebrow'>WORKSPACE</div>", unsafe_allow_html=True)
    for key, label, target in (
        ("sidebar_dashboard", "대시보드", "dashboard"),
        ("sidebar_rates", "지역별 흡연율", "dashboard"),
        ("sidebar_analysis", "관련 요인 분석", "analysis"),
        ("sidebar_policies", "금연정책 추천", "policies"),
        ("sidebar_location_review", "담배소매점 입지 평가", "location_review"),
    ):
        active = page == target and key != "sidebar_rates"
        st.button(f"● {label}" if active else label, type="tertiary", key=key, on_click=navigate, args=(target,))
    st.markdown("<div style='height:34px'></div>", unsafe_allow_html=True)
    st.markdown("<div class='eyebrow'>ABOUT</div>", unsafe_allow_html=True)
    st.markdown("[데이터 출처](DATA_SOURCES.txt)")
    st.caption("SmokeControl MVP · 지역사회건강조사")


if page == "location_review":
    from tobacco_location_official_csv.app import render_location_review

    render_location_review(retail_source=ROOT / "data" / "기타_담배소매업.csv")
    st.stop()


rates = load_rates()
geo = load_boundaries()
sido_geo = load_sido_boundaries()
district_features = {str(feature["properties"]["adm_cd"]): feature["properties"]
                     for feature in geo.get("features", []) if "adm_cd" in feature.get("properties", {})}
years = available_years(rates) or [2025]


if page in {"analysis", "policies"}:
    selected_region = st.session_state.get("selected_region")
    code = str(selected_region) if selected_region is not None else None
    feature = district_features.get(code)
    if feature is None:
        st.title("흡연 관련 요인 분석" if page == "analysis" else "금연정책 추천")
        st.info("대시보드 지도에서 시·군·구를 선택하세요.")
        st.stop()

    _, map_year = st.session_state.get("analysis_map_filters", (feature["sido"], 2025))
    if page == "policies":
        st.button("← 지역 분석으로 돌아가기", on_click=navigate, args=("analysis",))
        policy_years = METRIC_YEARS["tobacco"]
        initial_year = map_year if map_year in policy_years else policy_years[-1]
        year = st.selectbox("정책 추천 기준연도", policy_years, index=policy_years.index(initial_year))
        try:
            profile = build_region_profile(code, feature["sido"], feature["sigungu"], year)
        except (OSError, ValueError, KeyError):
            st.error("선택한 지역의 정책 추천 분석 자료를 읽을 수 없습니다.")
        else:
            render_ai_policy_recommendations(profile)
    else:
        st.button("← 지도 대시보드로 돌아가기", on_click=navigate, args=("dashboard",))
        analysis_year = render_analysis(code, feature["sido"], feature["sigungu"], map_year)
        if analysis_year is not None:
            st.button("금연정책 추천 보기", key="open_policy_report", on_click=navigate, args=("policies",))
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
            if province != "전국" and props.get("sido") != province:
                continue
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
    st.button("분석하기", type="primary", disabled=selected_code not in district_features,
              use_container_width=True, key="open_district_analysis", on_click=navigate, args=("analysis",))
    if not selected_code:
        st.caption("지도에서 시·군·구를 선택하면 관련 요인을 분석할 수 있습니다.")
    elif year < 2023:
        st.caption("관련 요인 분석은 2023~2025년 자료를 사용합니다.")

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
            if not selected_code:
                st.caption("지도에서 시·군·구를 선택하세요.")
            else:
                name = district_features.get(selected_code, {}).get("sigungu", selected_code)
                st.markdown("---")
                st.markdown(f"**선택 시·군·구**  \n{name}")
                st.metric("담배제품 현재사용률", "데이터 없음" if selected_value is None else f"{selected_value:.1f}%")
                st.caption(f"{year}년 · 공식 표준화율")
        st.markdown("---")
        st.markdown("**지표 안내**")
        st.caption("일반담배 또는 전자담배 등 조사에서 정의한 담배제품을 하나 이상 현재 사용하는 비율입니다. 담배 유형별 사용률을 합산하지 않습니다.")

if not geo.get("features") or not sido_geo.get("features"):
    st.warning("행정경계 GeoJSON을 찾지 못했습니다. data/processed 경계 파일을 확인하세요.")
if rates.empty:
    st.warning("검증된 지역별 통계 파일이 없어 수치를 표시하지 않습니다.")
