import pandas as pd
from src.data_validator import validate_rates,match_diagnostics
def test_duplicates_and_invalid_rates_reported():
    df=pd.DataFrame([{"year":2025,"sido":"서울특별시","sigungu":"종로구","adm_cd":"11110","rate":101},{"year":2025,"sido":"서울특별시","sigungu":"종로구","adm_cd":"11110","rate":18}])
    issues=validate_rates(df); assert any("중복" in x for x in issues) and any("범위" in x for x in issues)
def test_missing_rates_do_not_match_by_name():
    geo={"type":"FeatureCollection","features":[{"properties":{"SIG_CD":"11110"}}]}; rates=pd.DataFrame(columns=["year","adm_cd"])
    assert match_diagnostics(geo,rates)["matched"]==0
