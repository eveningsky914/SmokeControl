from src.region_utils import PROVINCES,province_from_code,normalize_code
def test_18_region_options(): assert len(PROVINCES)==18 and PROVINCES[0]=="전국"
def test_province_code(): assert province_from_code("11110")=="서울특별시"
def test_codes_are_strings(): assert normalize_code("11110.0")=="11110"
