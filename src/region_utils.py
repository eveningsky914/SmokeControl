PROVINCES = ["전국", "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"]
PROVINCE_CODES = {"11":"서울특별시", "21":"부산광역시", "22":"대구광역시", "23":"인천광역시", "24":"광주광역시", "25":"대전광역시", "26":"울산광역시", "29":"세종특별자치시", "31":"경기도", "32":"강원특별자치도", "33":"충청북도", "34":"충청남도", "35":"전북특별자치도", "36":"전라남도", "37":"경상북도", "38":"경상남도", "39":"제주특별자치도"}

def province_from_code(code):
    value = str(code).strip()
    return PROVINCE_CODES.get(value[:2]) if len(value) >= 2 else None

def normalize_code(code):
    value = str(code).strip()
    return value[:-2] if value.endswith(".0") else value
