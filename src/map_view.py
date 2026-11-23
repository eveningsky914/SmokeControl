"""Folium choropleth construction for the existing rate and boundary data."""

from copy import deepcopy

import folium
from folium.features import GeoJsonTooltip

from .region_utils import province_from_code


RATE_COLORS = ["#dbeafe", "#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#1d4ed8"]


def _rate_color(value):
    if value is None:
        return "#e5e7eb"
    if value < 16:
        return RATE_COLORS[0]
    if value < 18:
        return RATE_COLORS[1]
    if value < 20:
        return RATE_COLORS[2]
    if value < 22:
        return RATE_COLORS[3]
    if value < 24:
        return RATE_COLORS[4]
    return RATE_COLORS[5]


def build_map(geo, rates, year, province, selected_code=None, sido_geo=None):
    """Build a map while preserving the app's existing click/selection workflow."""
    province_level = province == "전국"
    if province_level and sido_geo is not None:
        geo = sido_geo

    m = folium.Map(
        location=[36.3, 127.8],
        zoom_start=7,
        # Avoid Carto basemaps, which now require an API key and render a key banner.
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )
    if not geo.get("features"):
        folium.Marker(
            [36.3, 127.8],
            tooltip="공식 경계 GeoJSON을 data/processed에 설치하면 지도에 표시됩니다.",
        ).add_to(m)
        return m

    geo = deepcopy(geo)
    if not province_level:
        geo["features"] = [
            feature
            for feature in geo["features"]
            if province_from_code(
                feature.get("properties", {}).get("adm_cd")
                or feature.get("properties", {}).get("SIG_CD")
                or feature.get("properties", {}).get("SIGUNGU_CD")
                or feature.get("properties", {}).get("sigungu_code")
                or ""
            ) == province
        ]

    frame = rates[rates["year"] == year] if not rates.empty else rates
    if not frame.empty and "level" in frame:
        frame = frame[frame["level"] == ("sido" if province_level else "sigungu")]
    by_code = {str(row.adm_cd): row for row in frame.itertuples()} if not frame.empty else {}

    for feature in geo["features"]:
        props = feature.setdefault("properties", {})
        code = str(
            props.get("adm_cd")
            or props.get("SIG_CD")
            or props.get("SIGUNGU_CD")
            or props.get("sigungu_code")
            or ""
        )
        row = by_code.get(code)
        if province_level:
            props["map_name"] = props.get("sido") or props.get("SIDO_NM") or props.get("name") or "이름 미상"
        else:
            props["map_name"] = (
                props.get("sigungu")
                or props.get("SIGUNGU_NM")
                or props.get("SIG_KOR_NM")
                or props.get("name")
                or "이름 미상"
            )
        rate = getattr(row, "rate", None) if row is not None else None
        if rate is not None:
            try:
                rate = float(rate)
                if rate != rate:
                    rate = None
            except (TypeError, ValueError):
                rate = None
        props["rate_display"] = f"{rate:.1f}%" if rate is not None else "데이터 없음"
        props["adm_cd"] = code
        props["fill_rate"] = rate

    def style(feature):
        props = feature["properties"]
        if selected_code and props["adm_cd"] == str(selected_code):
            return {"fillColor": "#4f6ef7", "color": "#1837b8", "weight": 3, "fillOpacity": 0.96}
        return {
            "fillColor": _rate_color(props["fill_rate"]),
            "color": "#ffffff",
            "weight": 1.1,
            "fillOpacity": 0.9,
        }

    layer = folium.GeoJson(
        geo,
        name="담배제품 현재사용률",
        style_function=style,
        highlight_function=lambda _: {
            "color": "#2563eb",
            "weight": 3,
            "fillColor": "#3b82f6",
            "fillOpacity": 0.94,
        },
        tooltip=GeoJsonTooltip(
            fields=["map_name", "rate_display"],
            aliases=["행정구역", "담배제품 현재사용률"],
            sticky=True,
            style=(
                "background-color: #fff; color: #17191f; font-family: 'Noto Sans KR', sans-serif;"
                "font-size: 12px; padding: 9px 11px; border: 1px solid #e9eaee; border-radius: 8px;"
            ),
        ),
    ).add_to(m)

    try:
        bounds = layer.get_bounds()
        if bounds and bounds[0]:
            m.fit_bounds(bounds, padding=(18, 18))
    except Exception:
        pass

    # SGIS label points are used as supplied; no geometry or rate data is changed.
    for feature in geo["features"]:
        props = feature.get("properties", {})
        point = props.get("label_point")
        if point and len(point) == 2:
            label = f"{props['map_name']}<br>{props['rate_display']}"
            folium.Marker(
                [point[1], point[0]],
                interactive=False,
                icon=folium.DivIcon(
                    icon_size=(120, 30),
                    icon_anchor=(60, 15),
                    html=(
                        "<div style='font-family:Noto Sans KR,sans-serif;font-size:10px;line-height:1.25;"
                        "font-weight:600;color:#253044;text-align:center;white-space:nowrap;"
                        "text-shadow:0 1px 2px #fff,1px 0 2px #fff,-1px 0 2px #fff'>"
                        f"{label}</div>"
                    ),
                ),
            ).add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    legend_html = """
    <div style="position:fixed;bottom:26px;left:18px;z-index:9999;background:#fff;
      padding:10px 12px;border:1px solid #e5e7eb;border-radius:9px;color:#374151;
      font:12px 'Noto Sans KR',sans-serif;box-shadow:0 1px 4px #00000012">
      <b>담배제품 현재사용률</b><br>
      <span style="color:#dbeafe">■</span> &lt;16% &nbsp;
      <span style="color:#93c5fd">■</span> 18–20% &nbsp;
      <span style="color:#3b82f6">■</span> 22–24% &nbsp;
      <span style="color:#1d4ed8">■</span> ≥24%<br>
      <span style="color:#9ca3af">■</span> 데이터 없음
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    return m
