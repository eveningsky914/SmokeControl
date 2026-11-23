from src.data_loader import load_boundaries, load_rates, load_sido_boundaries, available_years
from src.map_view import build_map
import folium


def test_imported_official_years_and_levels():
    rates = load_rates()
    assert available_years(rates) == list(range(2019, 2026))
    assert set(rates["level"]) == {"national_median", "sido", "sigungu"}
    assert len(rates[(rates.year == 2025) & (rates.level == "sigungu")]) == 245
    national = rates[(rates.year == 2025) & (rates.level == "national_median")]
    assert national.rate.iloc[0] == 22.1


def test_imported_boundaries_and_known_missing_regions():
    geo = load_boundaries()
    assert len(geo["features"]) == 252
    codes = {str(f["properties"]["adm_cd"]) for f in geo["features"]}
    assert {"35011", "35012", "38111", "38112", "38113", "38114", "38115"}.issubset(codes)


def test_national_map_uses_17_provinces():
    rates = load_rates()
    sido_geo = load_sido_boundaries()
    assert len(sido_geo["features"]) == 17
    map_obj = build_map(load_boundaries(), rates, 2025, "전국", sido_geo=sido_geo)
    layer = next(item for item in map_obj._children.values() if isinstance(item, folium.GeoJson))
    names = {feature["properties"]["map_name"] for feature in layer.data["features"]}
    assert "서울특별시" in names and "부산광역시" in names and "전체" not in names
    html = map_obj.get_root().render()
    assert "SIDO-11" in html and "24.7%" in html
    assert "tile.openstreetmap.org" in html and "basemaps/api" not in html
