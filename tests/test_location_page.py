from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


def test_location_sidebar_opens_review_and_restores_dashboard_filters(tmp_path):
    from tobacco_location_official_csv import app as location_page

    root = Path(__file__).resolve().parents[1]
    with (
        patch("streamlit_folium.st_folium", return_value={}),
        patch.object(location_page, "st_folium", return_value={}),
        patch.object(location_page, "DATA", tmp_path),
        patch.object(location_page, "read_index", side_effect=ValueError("test fixture")),
    ):
        app = AppTest.from_file(str(root / "app.py"), default_timeout=30).run()
        assert not app.exception
        app.selectbox(key="province").set_value("서울특별시").run()
        app.selectbox(key="year").set_value("2024").run()

        sidebar = list(app.sidebar.children.values())
        menu = app.button(key="sidebar_location_review")
        menu_index = sidebar.index(menu)
        assert sidebar[menu_index - 1].label == "금연정책 추천"
        assert any("ABOUT" in item.value for item in sidebar[menu_index + 1:] if item.type == "markdown")
        assert [button.label.lstrip("● ") for button in app.sidebar.button] == [
            "대시보드", "지역별 흡연율", "관련 요인 분석", "금연정책 추천", "담배소매점 입지 평가"
        ]
        assert all(button.proto.type == "tertiary" for button in app.sidebar.button)

        menu.click().run()
        assert not app.exception
        assert app.title[0].value == "전국 담배소매점 및 무인담배판매기 타당성 평가"
        assert app.text_input[0].label == "주소 검색"
        assert not app.sidebar.get("text_input")

        app.button(key="sidebar_dashboard").click().run()
        assert not app.exception
        assert app.title[0].value == "지역 흡연 현황"
        assert app.selectbox(key="province").value == "서울특별시"
        assert app.selectbox(key="year").value == 2024

        app.button(key="sidebar_analysis").click().run()
        assert app.title[0].value == "흡연 관련 요인 분석"
        assert any("시·군·구를 선택" in message.value for message in app.info)
        app.button(key="sidebar_policies").click().run()
        assert app.title[0].value == "금연정책 추천"
        assert any("시·군·구를 선택" in message.value for message in app.info)
        app.button(key="sidebar_rates").click().run()
        assert not app.exception
        assert app.title[0].value == "지역 흡연 현황"
        assert app.selectbox(key="province").value == "서울특별시"
        assert app.selectbox(key="year").value == 2024
