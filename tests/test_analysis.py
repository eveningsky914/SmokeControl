import pandas as pd

from src.analysis import build_seoul_analysis, parse_estimate


def test_parse_official_estimate_and_standard_error():
    assert parse_estimate("20.8(1.5)") == (20.8, 1.5)
    assert parse_estimate("-")[0] != parse_estimate("-")[0]


def test_seoul_peer_analysis_uses_selected_district_and_rank_association():
    rates = pd.DataFrame(
        [
            {"year": 2025, "level": "sigungu", "sido": "서울특별시", "sigungu": name, "adm_cd": code, "rate": rate}
            for name, code, rate in [("가구", "11010", 10), ("나구", "11020", 20), ("다구", "11030", 30), ("라구", "11040", 40)]
        ]
    )
    indicators = pd.DataFrame(
        {"sigungu": ["가구", "나구", "다구", "라구"], "factor": ["걷기 실천율"] * 4, "value": [40, 50, 60, 70]}
    )
    shops = pd.DataFrame({"sigungu": ["가구", "나구", "다구", "라구"], "retailer_count": [10, 20, 30, 40]})
    population = pd.DataFrame({"adm_cd": ["11010", "11020", "11030", "11040"], "population": [10000] * 4})

    result = build_seoul_analysis(rates, indicators, shops, population, "11040")

    assert result["district"] == "라구"
    assert result["rate"] == 40
    assert result["peer_median"] == 25
    assert result["rank"] == 1
    walking = result["factors"].set_index("변수").loc["걷기 실천율"]
    assert walking["흡연율과의 Spearman ρ"] == 1


def test_analysis_rejects_unmatched_region():
    rates = pd.DataFrame(
        [{"year": 2025, "level": "sigungu", "sido": "서울특별시", "sigungu": "가구", "adm_cd": "11010", "rate": 15}]
    )
    empty = pd.DataFrame(columns=["sigungu", "factor", "value"])
    shops = pd.DataFrame(columns=["sigungu", "retailer_count"])
    population = pd.DataFrame(columns=["adm_cd", "population"])

    try:
        build_seoul_analysis(rates, empty, shops, population, "99999")
    except ValueError as exc:
        assert "선택한 지역" in str(exc)
    else:
        raise AssertionError("unmatched region should be rejected")
