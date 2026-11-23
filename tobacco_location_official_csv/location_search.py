"""선택적으로만 사용하는 OSM Nominatim 주소 검색. 주변시설 조회(Overpass) 없음."""
import requests


def search_address(query: str):
    query = query.strip()
    if len(query) < 2:
        return [], "검색어를 2글자 이상 입력하세요."
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "jsonv2", "countrycodes": "kr", "limit": 5, "accept-language": "ko"},
            headers={"User-Agent": "KoreaTobaccoLocationStudentProject/1.0 (educational noncommercial; contact: user-local)",
                     "Accept": "application/json"},
            timeout=(4, 12),
        )
        response.raise_for_status()
        data = response.json()
        output = []
        for item in data:
            try:
                lat, lon = float(item["lat"]), float(item["lon"])
                if 32 <= lat <= 39.5 and 123 <= lon <= 133:
                    output.append({"lat": lat, "lon": lon, "label": str(item.get("display_name", query))})
            except (KeyError, ValueError, TypeError):
                continue
        return output, None
    except (requests.RequestException, ValueError) as exc:
        return [], f"주소 검색 실패({type(exc).__name__}). 지도 클릭 또는 지역 바로 가기를 이용하세요."
