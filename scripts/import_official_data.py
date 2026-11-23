"""Import KDCA CHS rates and SGIS boundaries from user-provided official files.

The KDCA workbook does not expose administrative codes. Matching therefore uses
the unique pair (official province label, official locality label) against the
SGIS code/name crosswalk. No aggregation or name-only matching is performed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROVINCE_ALIAS = {
    "서울":"서울특별시", "부산":"부산광역시", "대구":"대구광역시", "인천":"인천광역시",
    "광주":"광주광역시", "대전":"대전광역시", "울산":"울산광역시", "세종":"세종특별자치시",
    "경기":"경기도", "강원":"강원특별자치도", "충북":"충청북도", "충남":"충청남도",
    "전북":"전북특별자치도", "전남":"전라남도", "경북":"경상북도", "경남":"경상남도",
    "제주":"제주특별자치도",
}
PROVINCE_CODES = {
    "11":"서울특별시", "21":"부산광역시", "22":"대구광역시", "23":"인천광역시",
    "24":"광주광역시", "25":"대전광역시", "26":"울산광역시", "29":"세종특별자치시",
    "31":"경기도", "32":"강원특별자치도", "33":"충청북도", "34":"충청남도",
    "35":"전북특별자치도", "36":"전라남도", "37":"경상북도", "38":"경상남도", "39":"제주특별자치도",
}
YEARS = range(2019, 2026)
OFFICIAL_MEDIANS = {2019:21.6, 2020:21.5, 2021:21.5, 2022:22.2, 2023:22.2, 2024:22.6, 2025:22.1}


def find_book(pattern: str) -> Path:
    found = list(DATA.glob(pattern))
    if len(found) != 1:
        raise FileNotFoundError(f"{pattern}: 파일 1개가 필요하지만 {len(found)}개 발견")
    return found[0]


def find_tobacco_sheet(path: Path) -> str:
    xls = pd.ExcelFile(path)
    candidates = [s for s in xls.sheet_names if "담배제품" in s and "남자" not in s]
    if len(candidates) != 1:
        raise ValueError(f"담배제품 사용 시트를 단일하게 찾지 못했습니다: {candidates}")
    return candidates[0]


def parse_estimate(value: object) -> tuple[float | None, float | None, str | None]:
    if pd.isna(value):
        return None, None, None
    raw = str(value).strip()
    match = re.match(r"^(\d+(?:\.\d+)?)\s*(\*{1,2})?\s*(?:\((\d+(?:\.\d+)?)\))?", raw)
    if not match:
        return None, None, raw
    return float(match.group(1)), float(match.group(3)) if match.group(3) else None, match.group(2)


def extract_sigungu(path: Path, boundary: gpd.GeoDataFrame) -> tuple[list[dict], dict]:
    sheet = find_tobacco_sheet(path)
    table = pd.read_excel(path, sheet_name=sheet, header=None)
    # Year groups start at row 11. Each has N, crude rate, standardized rate.
    year_col = {}
    for col, year in enumerate(table.iloc[11].tolist()):
        if pd.notna(year) and isinstance(year, (int, float)) and int(year) in YEARS:
            year_col[int(year)] = col + 2
    if set(year_col) != set(YEARS):
        raise ValueError(f"연도 열을 2019~2025로 확인하지 못했습니다: {year_col}")

    crosswalk: dict[tuple[str, str], list[str]] = {}
    for r in boundary.itertuples():
        code = str(r.SIGUNGU_CD)
        sido = PROVINCE_CODES.get(code[:2])
        if sido:
            crosswalk.setdefault((sido, str(r.SIGUNGU_NM).strip()), []).append(code)

    output = []
    stat_keys = set()
    matched_pairs = set()
    unmatched_rows = []
    duplicates = []
    for index in range(13, len(table)):
        short_sido, locality = table.iat[index, 0], table.iat[index, 1]
        if pd.isna(short_sido) or pd.isna(locality):
            continue
        sido = PROVINCE_ALIAS.get(str(short_sido).strip())
        locality = str(locality).strip()
        if not sido:
            continue
        key = (sido, locality)
        stat_keys.add(key)
        codes = crosswalk.get(key, [])
        if len(codes) != 1:
            unmatched_rows.append({"sido":sido, "sigungu":locality, "reason":"경계 코드 단일 매칭 실패", "candidate_codes":codes})
            continue
        code = codes[0]
        matched_pairs.add(key)
        for year, col in year_col.items():
            estimate, se, flag = parse_estimate(table.iat[index, col])
            if estimate is None:
                continue
            record_key=(year, code)
            if any(x["year"] == year and x["adm_cd"] == code for x in output):
                duplicates.append({"year":year,"adm_cd":code,"sido":sido,"sigungu":locality})
                continue
            n = pd.to_numeric(table.iat[index, col-2], errors="coerce")
            output.append({"year":year,"level":"sigungu","sido":sido,"sigungu":locality,
                           "adm_cd":code,"rate":estimate,"std_error":se,"sample_n":int(n) if pd.notna(n) else None,
                           "rate_type":"표준화율","quality_flag":flag or "",
                           "source":"KDCA 2025 지역사회 건강통계 부록표 2-3"})
    info={"sheet":sheet,"table_rows":len(stat_keys),"stat_keys":len(stat_keys),
          "matched_stat_keys":len(matched_pairs),"unmatched_stat_rows":unmatched_rows,
          "duplicate_rows":duplicates,"year_columns":year_col}
    return output, info


def extract_sido(path: Path) -> list[dict]:
    sheet=find_tobacco_sheet(path)
    table=pd.read_excel(path,sheet_name=sheet,header=None)
    result=[]
    for i in range(11,len(table)-2):
        short=table.iat[i,2]
        if pd.isna(short) or str(short).strip() not in PROVINCE_ALIAS:
            continue
        sido=PROVINCE_ALIAS[str(short).strip()]
        # The aggregate is reported on the row labelled '전체' / '(표준화율)'.
        target=None
        for j in range(i+1,min(i+5,len(table))):
            if "표준화율" in str(table.iat[j,4]) and str(table.iat[j-1,3]).strip()=="전체":
                target=j; break
        if target is None:
            continue
        for year in YEARS:
            col=16+(year-2019)
            estimate,se,flag=parse_estimate(table.iat[target,col])
            if estimate is not None:
                result.append({"year":year,"level":"sido","sido":sido,"sigungu":"전체",
                               "adm_cd":"SIDO-"+str(next(k for k,v in PROVINCE_CODES.items() if v==sido)),
                               "rate":estimate,"std_error":se,"sample_n":None,"rate_type":"표준화율",
                               "quality_flag":flag or "","source":"KDCA 2025 지역사회 건강통계 부록표 1-3"})
    if len(result) != 17*len(YEARS):
        raise ValueError(f"시도 표준화율 추출 수가 예상과 다릅니다: {len(result)}")
    return result


def main() -> None:
    sigungu_book=find_book("*시군구별*건강행태.xlsx")
    sido_book=find_book("*시도별*건강행태.xlsx")
    shp=find_book("국가데이터처_SGIS 행정구역 통계 및 경계/**/bnd_sigungu_*.shp")
    sido_shp=find_book("국가데이터처_SGIS 행정구역 통계 및 경계/**/bnd_sido_*.shp")
    boundary=gpd.read_file(shp)
    sido_boundary=gpd.read_file(sido_shp)
    if boundary.crs is None:
        raise ValueError("SGIS SHP CRS가 정의되지 않았습니다.")
    if not {"SIGUNGU_CD","SIGUNGU_NM"}.issubset(boundary.columns):
        raise ValueError(f"SGIS SHP 코드/명칭 컬럼 확인 실패: {list(boundary.columns)}")
    if not {"SIDO_CD","SIDO_NM"}.issubset(sido_boundary.columns):
        raise ValueError(f"SGIS 시도 SHP 코드/명칭 컬럼 확인 실패: {list(sido_boundary.columns)}")
    sigungu, diag=extract_sigungu(sigungu_book,boundary)
    sido=extract_sido(sido_book)
    national=[{"year":y,"level":"national_median","sido":"전국","sigungu":"시·군·구 중앙값",
               "adm_cd":"KR-MEDIAN","rate":v,"std_error":None,"sample_n":None,
               "rate_type":"시·군·구 중앙값","quality_flag":"",
               "source":"KDCA 2025 지역사회건강조사 결과 발표"} for y,v in OFFICIAL_MEDIANS.items()]
    rates=pd.DataFrame(national+sido+sigungu)
    dup=rates.duplicated(["year","adm_cd"],keep=False)
    if dup.any():
        raise ValueError("연도·행정구역 코드 중복 발견:\n"+rates.loc[dup,["year","adm_cd","sigungu"]].to_string(index=False))

    # Add app's neutral property aliases while preserving the original SGIS fields.
    boundary=boundary.copy()
    boundary["adm_cd"]=boundary["SIGUNGU_CD"].astype(str)
    boundary["sigungu"]=boundary["SIGUNGU_NM"].astype(str)
    boundary["sido"]=[PROVINCE_CODES.get(str(c)[:2],"") for c in boundary["SIGUNGU_CD"]]
    label_points=boundary.geometry.representative_point().to_crs("EPSG:4326")
    boundary["label_point"]=[[float(pt.x),float(pt.y)] for pt in label_points]
    matched_codes=set(rates.loc[rates.level=="sigungu","adm_cd"])
    all_codes=set(boundary["adm_cd"])
    missing_geo=sorted(all_codes-matched_codes)
    geo_out=DATA/"processed"/"sigungu.geojson"
    rates_out=DATA/"processed"/"tobacco_rates.csv"
    audit_out=DATA/"processed"/"matching_audit.json"
    geo_out.parent.mkdir(parents=True,exist_ok=True)
    # Simplify in source projected CRS; keep the original SHP untouched.
    # SGIS is projected in EPSG:5179, so this tolerance is meters. Simplifying
    # after conversion to EPSG:4326 would interpret 35 as degrees and collapse
    # polygons into distorted triangles.
    simplified=boundary.copy()
    simplified["geometry"]=simplified.geometry.simplify(35,preserve_topology=True)
    geo4326=simplified.to_crs("EPSG:4326")
    geo4326.to_file(geo_out,driver="GeoJSON",index=False)
    sido_boundary=sido_boundary.copy()
    sido_boundary["adm_cd"]=["SIDO-"+str(c) for c in sido_boundary["SIDO_CD"]]
    sido_boundary["sido"]=[PROVINCE_CODES.get(str(c),"") for c in sido_boundary["SIDO_CD"]]
    sido_boundary["sigungu"]="전체"
    sido_labels=sido_boundary.geometry.representative_point().to_crs("EPSG:4326")
    sido_boundary["label_point"]=[[float(pt.x),float(pt.y)] for pt in sido_labels]
    sido_simplified=sido_boundary.copy()
    sido_simplified["geometry"]=sido_simplified.geometry.simplify(35,preserve_topology=True)
    sido_geo4326=sido_simplified.to_crs("EPSG:4326")
    sido_geo_out=DATA/"processed"/"sido.geojson"
    sido_geo4326.to_file(sido_geo_out,driver="GeoJSON",index=False)
    rates.to_csv(rates_out,index=False,encoding="utf-8-sig")
    year_counts={str(y):int(((rates.year==y)&(rates.level=="sigungu")).sum()) for y in YEARS}
    diag.update({"boundary_file":str(shp.relative_to(ROOT)),"boundary_crs_original":str(boundary.crs),
                 "boundary_crs_output":"EPSG:4326","boundary_regions":len(boundary),
                 "valid_stat_records_2025":int((rates.level=="sigungu").groupby(rates.year).sum().get(2025,0)),
                 "matched_boundary_codes":len(matched_codes),"unmatched_boundary_codes":missing_geo,
                 "matching_rate_boundary_coverage":len(matched_codes)/len(all_codes) if all_codes else None,
                 "matched_sigungu_records_by_year":year_counts,
                 "appended_province_records":len(sido),"appended_official_national_medians":len(national),
                 "rate_rows":len(rates),"output_rates":str(rates_out.relative_to(ROOT)),
                 "output_geojson":str(geo_out.relative_to(ROOT)),
                 "sido_boundary_file":str(sido_shp.relative_to(ROOT)),
                 "sido_boundary_regions":len(sido_boundary),
                 "output_sido_geojson":str(sido_geo_out.relative_to(ROOT)),
                 "unmatched_stat_rows":diag["unmatched_stat_rows"],"duplicate_rows":diag["duplicate_rows"]})
    audit_out.write_text(json.dumps(diag,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in diag.items() if k not in {"unmatched_stat_rows"}},ensure_ascii=False,indent=2))
    print("\nUnmatched geography rows:")
    for row in diag["unmatched_stat_rows"]: print(f"- {row['sido']} {row['sigungu']} ({row['reason']})")
    print("\nUnmatched boundary codes:")
    for code in missing_geo: print(f"- {code} {boundary.loc[boundary.adm_cd==code,'SIGUNGU_NM'].iloc[0]}")


if __name__=="__main__":
    main()
