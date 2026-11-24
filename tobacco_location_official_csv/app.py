"""전국 담배소매점 입지환경 분석 | 공식 공공데이터 전용, Overpass 의존 없음."""
from __future__ import annotations
from pathlib import Path
import html
import math

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

if __package__:
    from .analysis_core import SpatialDataset, analyze, haversine_m, normalize_dataset
    from .data_io import find_source
    from .education_zones import ABSOLUTE, RELATIVE, EducationZones, find_zone_archive
    from .location_search import search_address
else:
    from analysis_core import SpatialDataset, analyze, haversine_m, normalize_dataset
    from data_io import find_source
    from education_zones import ABSOLUTE, RELATIVE, EducationZones, find_zone_archive
    from location_search import search_address

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
FACILITY_LABELS = {
    "tobacco": "기존 담배소매점",
    "schools": "초·중·고등학교",
    "kindergartens": "유치원",
}
COLORS = {"tobacco": "#f97316", "schools": "#2563eb", "kindergartens": "#16a34a"}
ZONE_STYLES = {
    ABSOLUTE: {"color": "#dc2626", "fillColor": "#ef4444", "weight": 2, "fillOpacity": 0.34},
    RELATIVE: {"color": "#ca8a04", "fillColor": "#facc15", "weight": 2, "fillOpacity": 0.24},
}
DEFAULT = (37.5037, 126.7659)  # 시작 화면만 부천시청 부근. 데이터는 임의 생성하지 않음.
TITLE = "전국 담배소매점 및 무인담배판매기 타당성 평가"

@st.cache_resource(show_spinner="정식 공공데이터 불러오는 중...", max_entries=12)
def read_index(path: str, size: int, mtime_ns: int, kind: str, crs: str):
    raw = Path(path).read_bytes()
    frame, metadata = normalize_dataset(raw, kind, crs)
    return SpatialDataset.from_frame(frame), metadata

@st.cache_resource(show_spinner="교육환경보호구역 경계를 불러오는 중...", max_entries=1)
def load_zone_index(path: str, size: int, mtime_ns: int) -> EducationZones:
    return EducationZones.from_zip(Path(path))

@st.cache_data(ttl=86400, max_entries=60, show_spinner=False)
def cached_search(query: str):
    return search_address(query)


def move(lat: float, lon: float, label: str):
    if not (32 <= lat <= 39.5 and 123 <= lon <= 133):
        st.error("대한민국 범위의 위도·경도를 입력해 주세요.")
        return
    state = st.session_state.location_review
    state.update(lat=float(lat), lon=float(lon), place=str(label), map_rev=state["map_rev"] + 1)
    st.rerun()


def show_distance(value):
    if value is None or not math.isfinite(float(value)):
        return "확인 불가"
    return f"{value:,.0f}m" if value < 1000 else f"{value / 1000:.2f}km"


def toggle_zone_boundaries():
    state = st.session_state.location_review
    state["show_zone_boundaries"] = not state["show_zone_boundaries"]


def collect_nearby(lat: float, lon: float, radius: int, datasets: dict) -> pd.DataFrame:
    rows = []
    for kind, index in datasets.items():
        idxs, dists = index.near(lat, lon, radius)
        for idx, dist in zip(idxs, dists):
            site = index.frame.iloc[int(idx)]
            rows.append({"분류": kind, "명칭": str(site['name']), "주소": str(site['address']),
                         "위도": float(site['lat']), "경도": float(site['lon']),
                         "거리(m)": round(float(dist)), "출처": "공식 공공데이터"})
    if not rows:
        return pd.DataFrame(columns=["분류", "명칭", "주소", "위도", "경도", "거리(m)", "출처"])
    return pd.DataFrame(rows).sort_values("거리(m)").reset_index(drop=True)


def create_map(lat: float, lon: float, radius: int, nearby: pd.DataFrame, shown: list,
               zone_overlay: dict | None = None):
    m = folium.Map(location=[lat,lon], tiles="OpenStreetMap", zoom_start=15,
                   control_scale=True, prefer_canvas=True)
    folium.Circle([lat,lon], radius=radius, color="#2563eb", weight=2,
                  fill=True, fill_color="#2563eb", fill_opacity=0.045,
                  tooltip=f"시설 표시 반경 {radius:,}m").add_to(m)
    if zone_overlay and zone_overlay["features"]:
        folium.GeoJson(zone_overlay, name="교육환경보호구역", interactive=False,
                       style_function=lambda feature: ZONE_STYLES[feature["properties"]["code"]]).add_to(m)
    points = nearby[nearby['분류'].isin(shown)].head(1500)
    for row in points.itertuples(index=False):
        kind, name, addr, la, lo, distance, origin = row
        popup = (f"<b>{html.escape(FACILITY_LABELS[kind])}</b><hr>"
                 f"{html.escape(name)}<br>{html.escape(addr)}"
                 f"<br>후보지 직선거리: {int(distance):,}m")
        folium.CircleMarker(location=[la,lo], radius=6, color="white", weight=1.1,
                            fill=True, fill_color=COLORS[kind], fill_opacity=.95,
                            popup=folium.Popup(popup,max_width=320),
                            tooltip=f"{FACILITY_LABELS[kind]}: {html.escape(name)}").add_to(m)
    folium.Marker([lat,lon], tooltip="분석 중인 후보지", popup="지도 클릭으로 후보지 변경",
                  icon=folium.Icon(color="red",icon="map-marker",prefix="fa")).add_to(m)
    return m


def render_location_review(retail_source: Path | None = None):
    state = st.session_state.setdefault("location_review", {
        "lat": DEFAULT[0], "lon": DEFAULT[1], "place": "초기 위치 (부천)",
        "show_zone_boundaries": False, "map_rev": 0, "search_results": [], "search_error": None,
    })
    if retail_source is not None and not retail_source.is_file():
        retail_source = None

    st.title(TITLE)
    st.caption("지도에서 위치를 클릭하거나 주소를 검색해 주변 유치원·초중고·담배소매점을 확인하세요.")

    summary = st.container()
    map_tab, vending_tab, retail_tab, source_tab = st.tabs([
        "🗺️ 지도 클릭 분석", "무인 담배판매기", "신규 담배소매점", "📚 공공데이터 상태"
    ])
    with map_tab:
        with st.form("location_address_form", border=False):
            address_field, search_action = st.columns([4, 1])
            q = address_field.text_input("주소 검색", placeholder="예: 부천시 중동, 부산 해운대구 우동",
                                         label_visibility="collapsed")
            search = search_action.form_submit_button("🔎 주소 검색", use_container_width=True)
        if search:
            state['search_results'], state['search_error'] = cached_search(q)
        if state['search_error']:
            st.warning(state['search_error'])
        for i, item in enumerate(state['search_results']):
            if st.button(str(item["label"])[:55], key=f"location_address_result_{i}",use_container_width=True):
                move(item["lat"],item["lon"],item["label"][:80])
        map_view, map_settings = st.columns([3, 1])
        with map_settings:
            st.markdown("**지도 설정**")
            with st.expander("위도·경도 직접 입력"):
                with st.form("location_coord_form"):
                    la = st.number_input("위도", value=float(state['lat']), format="%.7f")
                    lo = st.number_input("경도", value=float(state['lon']), format="%.7f")
                    if st.form_submit_button("이 좌표 분석하기"):
                        move(la, lo, "직접 입력 위치")
            radius = st.slider("시설 표시 범위", 500, 3000, 1000, 100,
                               help="후보지를 중심으로 이 거리 안의 시설을 표시합니다.")
            min_gap = st.number_input("소매점 직선거리 비교값 (m)", min_value=50, value=50, step=1,
                                      help="관할 시·군·구의 거리 기준을 입력할 수 있습니다. 지도에는 좌표 간 직선거리를 표시합니다.")
            crs = st.selectbox("담배소매점 X/Y 원본 좌표계", ["EPSG:5174", "EPSG:5181", "EPSG:5179", "EPSG:5186"],
                               help="행정안전부 담배소매업 인허가 데이터의 X/Y는 일반적으로 EPSG:5174입니다.")
            st.divider()

    lat,lon = float(state['lat']),float(state['lon'])
    indices, meta_rows = {}, []
    for kind, label in FACILITY_LABELS.items():
        path = retail_source if kind == "tobacco" and retail_source is not None else find_source(DATA, kind)
        if not path:
            meta_rows.append({"종류":label, "자료":"미연결", "유효 좌표":0,"비고":"배포 데이터 파일 없음"})
            continue
        try:
            stat=path.stat()
            index,meta=read_index(str(path),stat.st_size,stat.st_mtime_ns,kind,crs)
            if len(index.frame):
                indices[kind]=index
            meta_rows.append({"종류":label,"자료":path.name,"유효 좌표":len(index.frame),
                              "비고":meta["좌표 방식"] + " / " + meta["상태 처리"]})
        except Exception as exc:
            summary.error(f"{label} 파일을 읽지 못했습니다: {exc}")
            meta_rows.append({"종류":label,"자료":path.name,"유효 좌표":0,"비고":str(exc)})

    summary.markdown(f"**분석 위치:** {state['place']} · `{lat:.6f}, {lon:.6f}`")
    if not indices:
        summary.warning("배포 데이터에서 시설 정보를 읽지 못했습니다.")
    missing = [label for kind, label in FACILITY_LABELS.items() if kind not in indices]
    if indices and missing:
        summary.info("미연결 또는 유효 좌표 없음 · " + ", ".join(missing))

    report = analyze(lat, lon, indices, min_gap=min_gap)
    nearby = collect_nearby(lat, lon, radius, indices)
    retailer = report["nearest"]["tobacco"]
    school_kinds = ("kindergartens", "schools")
    school_nearby = nearby[nearby["분류"].isin(school_kinds)]
    zone_path = find_zone_archive(DATA)
    zones = None
    vending_check = "보호구역 자료 없음"
    if zone_path is None:
        meta_rows.append({"종류": "교육환경보호구역", "자료": "미연결", "비고": "배포 데이터 파일 없음"})
    else:
        try:
            stat = zone_path.stat()
            zones = load_zone_index(str(zone_path), stat.st_size, stat.st_mtime_ns)
            vending_check = zones.status_at(lat, lon)
            meta_rows.append({"종류": "교육환경보호구역", "자료": zone_path.name,
                              "비고": f"경계 도형 {len(zones.records):,}개"})
        except Exception as exc:
            zones = None
            vending_check = "보호구역 자료 확인 필요"
            meta_rows.append({"종류": "교육환경보호구역", "자료": zone_path.name, "비고": str(exc)})
    vending_summary, retail_summary = summary.columns(2)
    vending_summary.metric("무인 담배판매기 설치 검토", vending_check)
    if zone_path is not None:
        vending_summary.caption("연결된 교육환경보호구역 자료 기준")
    retail_summary.metric("신규 담배소매점 지정 검토", report["retail_check"])
    if retailer is not None:
        site, distance = retailer
        retail_summary.caption(f"{site['name']} · 직선거리 {show_distance(distance)} · 기준 {min_gap:,}m 예비 검토")

    with map_tab:
        with map_settings:
            st.markdown("**지도에 표시할 시설**")
            shown=[]
            for kind, name in FACILITY_LABELS.items():
                if st.checkbox(f"● {name}",value=True,key=f"location_shown_{kind}"):
                    shown.append(kind)
            show_zones = state['show_zone_boundaries']
            button_label = "보호구역 경계 숨기기" if show_zones else "보호구역 경계 표시"
            st.button(button_label, key="location_toggle_zone_boundaries", disabled=zones is None,
                      on_click=toggle_zone_boundaries)
            if show_zones and zones is not None:
                st.caption("🔴 절대보호구역 · 🟡 상대보호구역")
            st.divider()
            st.markdown(f"**반경 {radius:,}m 실제 공공데이터**")
            for kind, name in FACILITY_LABELS.items():
                n=int((nearby['분류']==kind).sum())
                st.caption(f"{name}: {n:,}개" if kind in indices else f"{name}: 자료 미연결")
            if len(nearby)>1500:
                st.warning("성능을 위해 지도에는 가까운 1,500개만 보입니다. CSV 저장은 전체 목록을 포함합니다.")
        with map_view:
            zone_overlay = None
            if show_zones and zones is not None:
                try:
                    zone_overlay = zones.boundaries_near(lat, lon, radius)
                except Exception as exc:
                    st.warning(f"보호구역 경계를 표시하지 못했습니다: {exc}")
            result=st_folium(create_map(lat,lon,radius,nearby,shown,zone_overlay),height=570,
                             use_container_width=True,key=f"location_map_{state['map_rev']}",
                             returned_objects=["last_clicked"])
            clicked=(result or {}).get("last_clicked")
            if isinstance(clicked,dict):
                try:
                    nla,nlo=float(clicked["lat"]),float(clicked["lng"])
                    if haversine_m(lat,lon,[nla],[nlo])[0]>2:
                        move(nla,nlo,"지도에서 클릭한 위치")
                except (KeyError,ValueError,TypeError):
                    pass
        st.caption("빨간 핀은 후보지, 파란 원은 시설 표시 반경입니다. 시설 점은 연결된 CSV 좌표를 표시합니다.")
        st.subheader("선택 위치 주변 시설 목록")
        if nearby.empty:
            st.warning("현재 표시할 시설이 없습니다. 연결한 전국 CSV의 데이터 범위와 좌표 유효 여부를 확인하세요. 자료가 없다면 실제 주변에 시설이 없다는 뜻으로 해석할 수 없습니다.")
        else:
            view=nearby.copy()
            view['분류']=view['분류'].map(FACILITY_LABELS)
            st.dataframe(view[['분류','명칭','거리(m)','주소','출처']].head(1500),
                         use_container_width=True,hide_index=True)
            st.download_button("📥 주변 시설 목록 CSV 저장",view.to_csv(index=False).encode('utf-8-sig'),
                               file_name='선택지점_주변시설.csv',mime='text/csv')

    with vending_tab:
        st.subheader(vending_check)
        st.subheader("인근 유치원·학교")
        for kind in school_kinds:
            label = FACILITY_LABELS[kind]
            if kind not in indices:
                st.caption(f"{label} · CSV 미연결 또는 유효 좌표 없음")
            elif not (school_nearby["분류"] == kind).any():
                st.caption(f"{label} · 표시 반경 {radius:,}m 안에 등록된 좌표 없음")
        if not school_nearby.empty:
            view = school_nearby[["분류", "명칭", "거리(m)", "주소"]].copy()
            view["분류"] = view["분류"].map(FACILITY_LABELS)
            st.dataframe(view.rename(columns={"거리(m)": "시설 좌표까지 직선거리(m)"}),
                         use_container_width=True, hide_index=True)

    with retail_tab:
        st.subheader("가장 가까운 기존 담배소매점")
        if retailer is None:
            st.info("배포 데이터에서 기존 담배소매점 좌표를 읽지 못했습니다.")
        else:
            site, distance = retailer
            st.metric(str(site["name"]), show_distance(distance))
            if site["address"]:
                st.caption(str(site["address"]))
            st.write(f"직선거리 기준 {min_gap:,}m 예비 검토 · {report['retail_check']}")
        st.write("소매점 간 거리 기준과 측정 방법은 관할 시·군·구 규칙을 확인하세요. 지도 거리는 등록 좌표 간 직선거리입니다.")
        st.link_button("담배소매인 지정기준 보기", "https://law.go.kr/LSW/lumLsLinkPop.do?chrClsCd=010202&lspttninfSeq=57811")

    with source_tab:
        st.subheader("공식 데이터 연결 및 검증 결과")
        st.dataframe(pd.DataFrame(meta_rows),hide_index=True,use_container_width=True)
        st.write("배포 폴더에 포함된 데이터를 자동으로 읽고, 선택한 후보지 주변을 검색합니다.")
        st.markdown(
            "**분석 시 주의사항**\n\n"
            "- 담배소매업 자료는 영업상태·지정요건·좌표 누락 등에 따라 공백이 있을 수 있습니다.\n"
            "- 유치원과 학교는 공시된 시설 좌표를 표시합니다. 교육환경보호구역은 연결한 SHP ZIP의 경계로 확인합니다.\n"
            "- 소매인 지정 시 관할 지자체의 기준과 측정 방법이 적용됩니다.\n"
            "- **가상 판매점/학교는 포함하지 않습니다.** 임의 데이터로 적합 판정하지 않습니다."
        )


if __name__ == "__main__":
    st.set_page_config(page_title=TITLE, page_icon="📍", layout="wide")
    st.markdown("""<style>
.block-container{padding-top:1.25rem;max-width:1600px}
[data-testid="stMetricValue"]{font-size:1.3rem}
</style>""", unsafe_allow_html=True)
    render_location_review()
