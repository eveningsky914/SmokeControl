import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.smoking_comparison import compare_composition, weighted_rates
from src.data_loader import load_boundaries
from src.smoking_survey import outcomes


def test_crude_gap_is_additive_and_composition_contributions_reconcile():
    population = pd.DataFrame({"age_band": ["a", "b"], "count": [30, 70]})
    reference = pd.DataFrame({"age_band": ["a", "b"], "reference_count": [60, 40], "rate": [10, 30]})
    result = compare_composition(population, reference, 27, ["age_band"])
    assert result["reference"] == pytest.approx(18)
    assert result["expected"] == pytest.approx(24)
    assert result["composition"] == pytest.approx(6)
    assert result["remaining"] == pytest.approx(3)
    assert result["gap"] == pytest.approx(result["composition"] + result["remaining"])
    assert sum(cell["contribution"] for cell in result["cells"]) == pytest.approx(6)


def test_missing_stratum_never_rescales_population_or_fills_an_actual_rate():
    population = pd.DataFrame({"age_band": ["a", "b"], "count": [30, 70]})
    reference = pd.DataFrame({"age_band": ["a", "b"], "reference_count": [60, 40], "rate": [10, 30]})
    assert compare_composition(population, reference.iloc[:1], 27, ["age_band"]) is None
    result = compare_composition(population, reference, None, ["age_band"])
    assert result["expected"] == pytest.approx(24)
    assert result["remaining"] is None and result["gap"] is None


def test_weighted_rates_exclude_missing_outcomes_and_nonpositive_weights():
    frame = pd.DataFrame({"group": ["a"] * 4, "smoking": [1, 0, None, 1], "weight": [3, 1, 99, 0]})
    result = weighted_rates(frame, ["group"]).iloc[0]
    assert result.n == 2
    assert result.rate == pytest.approx(75)


def test_product_indicator_respects_structural_skips_and_missing_responses():
    raw = pd.DataFrame({
        "smf_01z1": [2, 1, 1, 1, 1], "sma_01z1": [8, 3, 2, 2, 3], "sma_03z2": [8, 8, 1, 7, 8],
        "sma_36z1": [8, 2, 2, 2, 2], "sma_37z1": [8, 8, 8, 8, 8],
        "sma_08z1": [8, 2, 2, 2, 1], "sma_11z2": [88, 88, 88, 88, 77], "sma_12z2": [8, 1, 9, 2, 2],
    })
    cigarette, product = outcomes(raw, 2025).values()
    assert cigarette.iloc[:3].tolist() == [0, 0, 1]
    assert pd.isna(cigarette.iloc[3])
    assert product.iloc[:2].tolist() == [0, 1]
    assert product.iloc[2:].isna().all()
    assert set(outcomes(raw, 2023)) == {"cigarette"}


def test_generated_analysis_for_non_seoul_district_uses_2025_adults():
    path = Path(__file__).resolve().parents[1] / "data/processed/national_smoking_analysis.json"
    if not path.exists():
        pytest.skip("Generate the local analysis artifact first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data["results"]["cigarette"]) == {"2023", "2024", "2025"}
    assert set(data["results"]["tobacco"]) == {"2024", "2025"}
    code = "32010"  # 춘천시
    report = data["results"]["cigarette"]["2025"]
    age = report["comparison"][code]["national_age"]
    sex_age = report["comparison"][code]["sample_sex_age"]
    assert age["actual"] == report["official"][code]["crude"]
    assert sum(cell["count"] for cell in age["cells"]) == sum(row["count"] for row in report["population"][code])
    assert data["metadata"]["population"]["2025"]["file"] == "population2025.csv"
    assert age["expected"] == pytest.approx(sum(cell["share"] * cell["rate"] for cell in age["cells"]))
    assert age["gap"] == pytest.approx(age["composition"] + age["remaining"])
    assert len(sex_age["cells"]) == 12
    assert report["comparison"]["38111"]["national_age"]["remaining"] is None
    assert report["comparison"]["38111"]["national_age"]["expected"] is not None
    assert 0 < report["sample_reference"]["adult_share"] < 1
    assert data["regional"]["cigarette"]["2024"]["model"]["n"] >= 40
    assert data["regional"]["cigarette"]["2025"]["stats"]["low_income"]["n"] == 0
    province_rates = [row for row in report["individual"] if row["scope"] == "province"
                      and row["sido"] == "강원특별자치도" and row["factor"] == "assistance"]
    assert {row["category"] for row in province_rates} == {"현재 수급", "현재 미수급"}
    assert not data["metadata"]["survey"]["2025"]["coverage"]["national"]["complete"]
    comparisons = data["region_comparisons"]
    assert comparisons["2024"]["baselines"]["전국"]["low_income"] == {"value": 4.99, "kind": "official"}
    assert comparisons["2024"]["baselines"]["충청북도"]["low_income"]["value"] == pytest.approx(5.13)
    assert comparisons["2025"]["baselines"]["충청북도"]["high_risk_drinking"]["kind"] == "official"
    assert comparisons["2025"]["baselines"]["전국"]["high_risk_drinking"]["kind"] == "median"
    retail = comparisons["2025"]["baselines"]["전국"]["retail"]
    expected_retail = data["metadata"]["retail"]["active_permits"] / data["metadata"]["population"]["2025"]["national_adults"] * 10_000
    assert retail["value"] == pytest.approx(expected_retail)


def test_dashboard_opens_nationwide_analysis_and_returns_to_map():
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    if not (root / "data/processed/national_smoking_analysis.json").exists():
        pytest.skip("Generate the local analysis artifact first.")
    district = next(feature["properties"] for feature in load_boundaries()["features"]
                    if feature["properties"]["adm_cd"] == "32010")
    lng, lat = district["label_point"]
    with patch("streamlit_folium.st_folium", return_value={}) as map_component:
        app = AppTest.from_file(str(root / "app.py"), default_timeout=20).run()
        assert not app.exception
        assert app.title[0].value == "지역 흡연 현황"
        assert app.button(key="open_district_analysis").disabled
        app.selectbox(key="province").set_value(district["sido"]).run()
        map_component.return_value = {"last_clicked": {"lng": lng, "lat": lat}}
        app.run()
        assert not app.button(key="open_district_analysis").disabled
        app.button(key="open_district_analysis").click().run()
        assert not app.exception
        assert app.title[0].value == "춘천시 흡연 관련 요인"
        metrics = {metric.label: metric.value for metric in app.metric}
        assert list(metrics)[:3] == ["실제 조사 흡연율", "예상 흡연율", "실제와 예상의 차이"]
        assert "지역 비교용 흡연율" in metrics
        assert metrics["실제와 예상의 차이"] != "자료 없음"
        assert any(panel.label == "다변량 로지스틱 회귀 · 제공 표본" for panel in app.expander)
        app.selectbox(key="analysis_peer_district_32010").set_value("11010").run()
        app.selectbox(key="analysis_person_factor").set_value("assistance").run()
        assert not app.exception
        tables = [table.value for table in app.dataframe]
        personal = next(table for table in tables if "비교 집단" in table and "우리 지역" in table)
        assert {"우리 지역", "전국 비교 · 제공 표본", "서울특별시 종로구"} <= set(personal)
        assert any(column.startswith("강원특별자치도") for column in personal)
        assert "현재 수급" in personal["비교 집단"].tolist()
        living = next(table for table in tables if "생활 여건" in table)
        assert {"우리 지역", "강원특별자치도", "전국", "서울특별시 종로구"} <= set(living)
        assert "주소 확인분" in living.loc[living["생활 여건"].str.contains("담배소매점"), "강원특별자치도"].item()
        app.radio(key="analysis_official_comparator").set_value("우리 지역이 속한 시·도").run()
        assert not app.exception
        assert any(metric.label == "우리 지역이 속한 시·도" and metric.value != "자료 없음" for metric in app.metric)
        app.radio(key="analysis_composition_reference").set_value("sample_sex_age").run()
        assert not app.exception
        assert any("성별과 나이대가 같은 제공 표본" in caption.value for caption in app.caption)
        app.selectbox(key="analysis_metric").set_value("tobacco").run()
        assert not app.exception
        assert any(metric.label == "실제 조사 담배제품 사용률" for metric in app.metric)
        assert app.selectbox(key="analysis_year_tobacco").options == ["2024", "2025"]
        next(button for button in app.button if button.label == "← 지도 대시보드로 돌아가기").click().run()
        assert not app.exception
        assert app.selectbox(key="province").value == district["sido"]
