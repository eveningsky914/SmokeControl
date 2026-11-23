"""전국 담배소매점 입지환경 분석 | 공식 공공데이터 전용, Overpass 의존 없음."""
from __future__ import annotations
from pathlib import Path
import html
import math

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from analysis_core import (KINDS, WEIGHTS, SpatialDataset, analyze,
                           grid_candidates, haversine_m, normalize_dataset)
from data_io import find_source, write_source, validate_raw
from location_search import search_address

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SOURCES = {
    "tobacco": ("기존 담배소매점", "https://www.data.go.kr/data/15045104/fileData.do"),
    "schools": ("초·중·고등학교", "https://www.data.go.kr/data/15021148/standard.do"),
    "zones": ("어린이보호구역 기준점", "https://www.data.go.kr/data/15012891/standard.do"),
}
COLORS = {"tobacco": "#f97316", "schools": "#2563eb", "zones": "#16a34a"}
DEFAULT = (37.5037, 126.7659)  # 시작 화면만 부천시청 부근. 데이터는 임의 생성하지 않음.
SHORTCUTS = {
    "부천": (37.5037,126.7659), "서울": (37.5665,126.9780), "인천": (37.4563,126.7052),
    "수원": (37.2636,127.0286), "대전": (36.3504,127.3845), "대구": (35.8714,128.6014),
    "부산": (35.1796,129.0756), "광주": (35.1595,126.8526), "울산": (35.5384,129.3114),
    "세종": (36.4801,127.2890), "춘천": (37.8813,127.7298), "청주": (36.6424,127.4890),
    "전주": (35.8242,127.1480), "창원": (35.2280,128.6811), "제주": (33.4996,126.5312),
}

st.set_page_config(page_title="전국 담배소매점 입지환경 분석", page_icon="📍", layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.25rem;max-width:1600px}
[data-testid="stMetricValue"]{font-size:1.3rem}
</style>""", unsafe_allow_html=True)

@st.cache_resource(show_spinner="정식 공공데이터 불러오는 중...", max_entries=12)
def read_index(path: str, size: int, mtime_ns: int, kind: str, crs: str):
    raw = Path(path).read_bytes()
    frame, metadata = normalize_dataset(raw, kind, crs)
    return SpatialDataset.from_frame(frame), metadata

@st.cache_data(ttl=86400, max_entries=60, show_spinner=False)
def cached_search(query: str):
    return search_address(query)


def move(lat: float, lon: float, label: str):
    if not (32 <= lat <= 39.5 and 123 <= lon <= 133):
        st.error("대한민국 범위의 위도·경도를 입력해 주세요.")
        return
    st.session_state.lat = float(lat)
    st.session_state.lon = float(lon)
    st.session_state.place = str(label)
    st.session_state.map_rev += 1
    st.rerun()


def show_distance(value):
    if value is None or not math.isfinite(float(value)):
        return "확인 불가"
    return f"{value:,.0f}m" if value < 1000 else f"{value / 1000:.2f}km"


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


def create_map(lat: float, lon: float, radius: int, nearby: pd.DataFrame, shown: list):
    m = folium.Map(location=[lat,lon], tiles="OpenStreetMap", zoom_start=15,
                   control_scale=True, prefer_canvas=True)
    folium.Circle([lat,lon], radius=radius, color="#2563eb", weight=2,
                  fill=True, fill_color="#2563eb", fill_opacity=0.045,
                  tooltip=f"시설 표시 반경 {radius:,}m").add_to(m)
    folium.Circle([lat,lon], radius=500, color="#ea580c", weight=2,
                  dash_array="5 5", fill=False, tooltip="500m 판매점 밀도 분석 범위").add_to(m)
    points = nearby[nearby['분류'].isin(shown)].head(1500)
    for row in points.itertuples(index=False):
        kind, name, addr, la, lo, distance, origin = row
        popup = (f"<b>{html.escape(SOURCES[kind][0])}</b><hr>"
                 f"{html.escape(name)}<br>{html.escape(addr)}"
                 f"<br>후보지 직선거리: {int(distance):,}m")
        folium.CircleMarker(location=[la,lo], radius=6, color="white", weight=1.1,
                            fill=True, fill_color=COLORS[kind], fill_opacity=.95,
                            popup=folium.Popup(popup,max_width=320),
                            tooltip=f"{SOURCES[kind][0]}: {html.escape(name)}").add_to(m)
    folium.Marker([lat,lon], tooltip="분석 중인 후보지", popup="지도 클릭으로 후보지 변경",
                  icon=folium.Icon(color="red",icon="map-marker",prefix="fa")).add_to(m)
    return m


for key, value in {"lat":DEFAULT[0], "lon":DEFAULT[1], "place":"초기 위치 (부천)",
                   "map_rev":0, "search_results":[], "search_error":None}.items():
    if key not in st.session_state:
        st.session_state[key] = value

st.title("📍 전국 담배소매점 입지환경 분석")
st.caption("전국 공공데이터 CSV 기반 · 지도를 클릭하면 그 위치의 실제 학교·담배소매점·보호구역 기준점을 즉시 분석 · Overpass API 사용 안 함")

with st.sidebar:
    st.header("① 위치 선택")
    place = st.selectbox("지역 바로 이동", ["지역 선택..."]+list(SHORTCUTS.keys()))
    if place != "지역 선택..." and st.button("선택한 지역으로 이동", use_container_width=True):
        la,lo = SHORTCUTS[place]
        move(la,lo,f"{place} 대표 위치")
    with st.form("address_form"):
        q = st.text_input("주소 검색 (선택 사항)", placeholder="예: 부천시 중동, 부산 해운대구 우동")
        search = st.form_submit_button("🔎 주소 검색",use_container_width=True)
    if search:
        st.session_state.search_results, st.session_state.search_error = cached_search(q)
    if st.session_state.search_error:
        st.warning(st.session_state.search_error)
    for i, item in enumerate(st.session_state.search_results):
        if st.button(str(item["label"])[:55], key=f"loc{i}",use_container_width=True):
            move(item["lat"],item["lon"],item["label"][:80])
    with st.expander("위도·경도 직접 입력"):
        with st.form("coord_form"):
            la = st.number_input("위도", value=float(st.session_state.lat),format="%.7f")
            lo = st.number_input("경도", value=float(st.session_state.lon),format="%.7f")
            if st.form_submit_button("이 좌표 분석하기"):
                move(la,lo,"직접 입력 위치")
    radius = st.slider("시설 표시 범위", 500,3000,1000,100,help="분석은 현재 클릭 위치 기준으로 계속 바뀝니다.")
    crs = st.selectbox("담배소매점 X/Y 원본 좌표계", ["EPSG:5174", "EPSG:5181", "EPSG:5179", "EPSG:5186"],
                       help="행정안전부 담배소매업 인허가 데이터의 X/Y는 일반적으로 EPSG:5174입니다.")
    st.divider()
    st.header("② 전국 공공데이터 연결")
    st.caption("데이터 3종은 전국 실제 공공데이터로 제공됩니다. 자동 다운로드에 실패한 경우 포털에서 CSV를 받아 아래에 올리세요.")
    with st.expander("📥 3종 CSV 다운로드 출처",expanded=True):
        for kind, (label, url) in SOURCES.items():
            st.markdown(f"- [{label} 원본 다운로드]({url})")
        st.caption("받은 파일은 이름을 바꾸지 않고 업로드해도 됩니다. CSV가 들어있는 ZIP도 지원합니다.")

    upl = {}
    for kind, (label, url) in SOURCES.items():
        upl[kind] = st.file_uploader(f"{label} CSV 또는 ZIP", type=["csv","zip"],key=f"up_{kind}")
    if st.button("💾 올린 CSV를 프로젝트 data/에 저장",use_container_width=True):
        imported = []
        for kind, upload in upl.items():
            if upload is None:
                continue
            try:
                data = upload.getvalue()
                validate_raw(data,kind)
                target = write_source(DATA,kind,data,upload.name.lower().endswith(".zip"))
                imported.append(f"{SOURCES[kind][0]} → {target.name}")
            except Exception as exc:
                st.error(f"{SOURCES[kind][0]}: {exc}")
        if imported:
            st.success("저장됨: " + ", ".join(imported))
            st.rerun()
        else:
            st.info("업로드한 CSV가 없습니다.")

lat,lon = float(st.session_state.lat),float(st.session_state.lon)
indices, meta_rows = {}, []
for kind,(label,url) in SOURCES.items():
    path=find_source(DATA,kind)
    if not path:
        meta_rows.append({"종류":label, "자료":"미연결", "유효 좌표":0,"비고":"CSV 업로드 필요"})
        continue
    try:
        stat=path.stat()
        index,meta=read_index(str(path),stat.st_size,stat.st_mtime_ns,kind,crs)
        if len(index.frame):
            indices[kind]=index
        meta_rows.append({"종류":label,"자료":path.name,"유효 좌표":len(index.frame),
                          "비고":meta["좌표 방식"] + " / " + meta["상태 처리"]})
    except Exception as exc:
        st.error(f"{label} 파일을 읽지 못했습니다: {exc}")
        meta_rows.append({"종류":label,"자료":path.name,"유효 좌표":0,"비고":str(exc)})

st.markdown(f"**분석 위치:** {st.session_state.place} · `{lat:.6f}, {lon:.6f}`")
if not indices:
    st.warning("**전국 실제 CSV가 아직 없습니다.** 지도 클릭은 가능하지만 시설은 표시되지 않습니다. 왼쪽에서 3종 CSV를 연결하세요. 가상 시설을 임의 생성하지 않습니다.")
elif_missing = [SOURCES[k][0] for k in KINDS if k not in indices]
if indices and elif_missing:
    st.info("일부 자료만 연결됨: " + ", ".join(elif_missing) + ". 연결된 자료는 정상 표시하고, 누락 지표는 점수를 보류합니다.")

report = analyze(lat,lon,indices,min_gap=50,show_radius_m=radius)
nearby=collect_nearby(lat,lon,radius,indices)
# 데이터가 일부 지역만 커버하거나 우연히 인근 좌표가 없으면 법적·정책적 평가로 단정하지 않음.
ready = (len(indices)==3 and report['used_weight']==100 and not report['coverage_unknown'])
metrics=st.columns(4)
metrics[0].metric("정책 입지점수 (시범)",f"{report['score']} / 100" if ready else "산정 보류")
metrics[1].metric("기존 소매점까지",show_distance(report['nearest']['tobacco']) if 'tobacco' in indices else "자료 없음")
metrics[2].metric("학교까지",show_distance(report['nearest']['schools']) if 'schools' in indices else "자료 없음")
metrics[3].metric("500m 공식 소매점",f"{report['count_500']:,}개" if 'tobacco' in indices else "자료 없음")
if ready:
    st.info("정책적 참고 점수이며 담배소매인 지정 허가 여부를 판정하는 값은 아닙니다. 보호구역 거리도 실제 경계가 아닌 공공데이터 기준점까지의 거리입니다.")
else:
    st.caption("세 자료가 정상 연결되고 각 시설 종류의 주변 데이터 범위가 확인될 때만 종합점수를 계산합니다.")

map_tab, detail_tab, grid_tab, source_tab=st.tabs(["🗺️ 지도 클릭 분석", "📏 거리·밀도", "🧮 주변 후보 비교", "📚 공공데이터 상태"])
with map_tab:
    a,b=st.columns([3,1])
    with b:
        st.markdown("**지도에 표시할 시설**")
        shown=[]
        for kind,(name,url) in SOURCES.items():
            if st.checkbox(f"● {name}",value=True,key=f"shown_{kind}"):
                shown.append(kind)
        st.divider()
        st.markdown(f"**반경 {radius:,}m 실제 공공데이터**")
        for kind,(name,url) in SOURCES.items():
            n=int((nearby['분류']==kind).sum())
            st.caption(f"{name}: {n:,}개" if kind in indices else f"{name}: 자료 미연결")
        if len(nearby)>1500:
            st.warning("성능을 위해 지도에는 가까운 1,500개만 보입니다. CSV 저장은 전체 목록을 포함합니다.")
    with a:
        st.write("**원하는 위치를 지도에서 클릭해봐. 클릭한 위치 주변으로 바로 다시 계산돼.**")
        result=st_folium(create_map(lat,lon,radius,nearby,shown),height=570,
                         use_container_width=True,key=f"map_{st.session_state.map_rev}",
                         returned_objects=["last_clicked"])
        clicked=(result or {}).get("last_clicked")
        if isinstance(clicked,dict):
            try:
                nla,nlo=float(clicked["lat"]),float(clicked["lng"])
                if haversine_m(lat,lon,[nla],[nlo])[0]>2:
                    move(nla,nlo,"지도에서 클릭한 위치")
            except (KeyError,ValueError,TypeError):
                pass
    st.caption("빨간 핀=분석 위치 · 파란색 원=표시 반경 · 주황 점선=소매점 밀도 500m 반경. 모든 시설 점은 연결된 공식 CSV의 좌표만 사용합니다.")
    st.subheader("선택 위치 주변 시설 목록")
    if nearby.empty:
        st.warning("현재 표시할 시설이 없습니다. 연결한 전국 CSV의 데이터 범위와 좌표 유효 여부를 확인하세요. 자료가 없다면 실제 주변에 시설이 없다는 뜻으로 해석할 수 없습니다.")
    else:
        view=nearby.copy()
        view['분류']=view['분류'].map({k:v[0] for k,v in SOURCES.items()})
        st.dataframe(view[['분류','명칭','거리(m)','주소','출처']].head(1500),
                     use_container_width=True,hide_index=True)
        st.download_button("📥 주변 시설 목록 CSV 저장",view.to_csv(index=False).encode('utf-8-sig'),
                           file_name='선택지점_주변시설.csv',mime='text/csv')

with detail_tab:
    vals=[("기존 담배소매점 최단거리",'tobacco'),("학교 최단거리",'schools'),("어린이보호구역 등록 기준점 최단거리",'zones')]
    tab=[]
    for label,kind in vals:
        tab.append({"지표":label,"결과":show_distance(report['nearest'][kind]) if kind in indices else 'CSV 미연결'})
    tab.extend([{"지표":"반경 500m 공식 담배소매점 수","결과":report['count_500'] if 'tobacco' in indices else '미확인'},
                {"지표":"반경 1km 공식 담배소매점 수","결과":report['count_1000'] if 'tobacco' in indices else '미확인'},
                {"지표":"500m 소매점 밀도 (개/km²)","결과":report['density_500'] if 'tobacco' in indices else '미확인'}])
    st.dataframe(pd.DataFrame(tab),use_container_width=True,hide_index=True)
    if ready:
        st.subheader("지표별 평가 구성")
        st.dataframe(pd.DataFrame([{"지표":k,"가중치(%)":w,"평가점수":report['components'].get(k)} for k,w in WEIGHTS.items()]),
                     use_container_width=True,hide_index=True)
    for warning in report['notes']:
        st.warning(warning)
    st.caption("소매점 간 50m 비교는 시범용 직선거리 검사이며 법적 허가 판정이나 실제 출입구 간 거리 측정이 아닙니다. 학교·보호구역 거리는 정책적 청소년 보호 지표입니다.")

with grid_tab:
    st.write("**선택지점 주변 81개 격자 비교** (실제 허가 가능한 점포/건물과 다름)")
    if not ready:
        st.info("공식 CSV 3종을 연결한 뒤 분석 대상 지역 데이터 범위가 확인되면 사용할 수 있어요.")
    elif st.button("81개 격자 비교 실행"):
        grid=grid_candidates(lat,lon,indices,radius_m=600,steps=9)
        st.dataframe(grid.head(81),use_container_width=True,hide_index=True)
        st.download_button("격자 결과 CSV 저장",grid.to_csv(index=False).encode('utf-8-sig'),
                           file_name="후보_격자분석.csv",mime="text/csv")

with source_tab:
    st.subheader("공식 데이터 연결 및 검증 결과")
    st.dataframe(pd.DataFrame(meta_rows),hide_index=True,use_container_width=True)
    st.write("이 프로그램은 매번 Overpass API를 호출하지 않습니다. CSV를 한번 연결하면 지도를 클릭할 때마다 컴퓨터에 저장된 공식 CSV에서 가까운 지점을 검색합니다.")
    st.markdown("""**분석 시 주의사항**

- 담배소매업 자료는 영업상태·지정요건·좌표 누락 등에 따라 공백이 있을 수 있습니다.
- 어린이보호구역은 제공된 **대표/기준점 좌표**를 표시하며 보호구역 폴리곤 경계와는 다릅니다.
- 법령상 지정 가능 여부는 거리측정 방법, 지자체별 조례/고시, 예외 조항, 현장 실사를 따로 확인해야 합니다.
- **가상 판매점/학교는 포함하지 않습니다.** 임의 데이터로 적합 판정하지 않습니다.
""")
    for kind,(label,url) in SOURCES.items():
        st.markdown(f"- [{label} : 공식 원본 다운로드]({url})")
