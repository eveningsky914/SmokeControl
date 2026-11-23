import pandas as pd
from src.map_view import build_map
def test_map_renders_without_boundary_data():
    m=build_map({"type":"FeatureCollection","features":[]},pd.DataFrame(),2025,"전국")
    assert "Leaflet" in m.get_root().render()
def test_map_has_boundary_tooltip():
    geo={"type":"FeatureCollection","features":[{"type":"Feature","properties":{"SIG_CD":"11110","SIG_KOR_NM":"종로구"},"geometry":{"type":"Polygon","coordinates":[[[126,37],[127,37],[127,38],[126,38],[126,37]]]}}]}
    rates=pd.DataFrame([{"year":2025,"sido":"서울특별시","sigungu":"종로구","adm_cd":"11110","rate":20.5}])
    html=build_map(geo,rates,2025,"서울특별시").get_root().render()
    # Folium JSON-escapes Korean text in its JavaScript payload, while the browser
    # renders it as Korean. Check the tooltip fields and value in serialized HTML.
    assert "20.5%" in html and "map_name" in html and "rate_display" in html
