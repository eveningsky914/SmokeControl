"""Read and match nationwide analysis inputs without modifying the source files."""

from __future__ import annotations

import re
from collections import Counter

import openpyxl
import pandas as pd

from .data_loader import load_boundaries, load_rates
from .region_utils import PROVINCE_CODES
from .smoking_comparison import AGE_BANDS, METRIC_YEARS, SEXES, age_band


PROVINCE_NAMES = dict(zip(
    ("서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
     "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"),
    PROVINCE_CODES.values(), strict=True,
))
PROVINCE_NAMES.update({name: name for name in PROVINCE_CODES.values()})
PROVINCE_NAMES.update({"강원도": "강원특별자치도", "전라북도": "전북특별자치도", "제주도": "제주특별자치도"})
FACTORS = {
    "low_income": ("국민기초생활보장수급자수율", "%", "경제적 취약성"),
    "employment": ("고용률", "%", "노동시장 참여"),
    "unemployment": ("실업률", "%", "고용 불안정"),
    "doctors": ("인구천명당 의료기관 종사 의사수", "명/천 명", "지역 의료 인력"),
    "manufacturing": ("제조업 종사자 수", "명/성인 천 명", "제조업 종사자 수를 주민등록 성인 인구로 나눈 값"),
    "parks": ("인구일인당 공원면적", "㎡/명", "물리적 환경"),
    "high_risk_drinking": ("고위험음주율", "%", "공식 건강행태 표준화율"),
    "stress": ("스트레스 인지율", "%", "공식 건강행태 표준화율"),
    "depression": ("연간 우울감 경험률", "%", "공식 건강행태 표준화율"),
    "older": ("65세 이상 성인 비중", "%", "인구구조"),
    "retail": ("영업 중 담배소매점 밀도", "개/성인 1만 명", "파일 기준 시점의 판매 환경"),
}
DB_FACTORS = {key: FACTORS[key][0] for key in ("low_income", "employment", "unemployment", "doctors", "manufacturing", "parks")}
HEALTH_FACTORS = {FACTORS[key][0]: key for key in ("high_risk_drinking", "stress", "depression")}
PROVINCE_HEALTH_SHEETS = {"8.": "high_risk_drinking", "17.": "stress", "18.": "depression"}
POPULATION_MONTH = 7


def source_file(data_dir, pattern):
    files = sorted(data_dir.glob(pattern))
    if len(files) != 1:
        raise FileNotFoundError(f"{pattern}: 자료 1개가 필요합니다. 발견 {len(files)}개")
    return files[0]


def area_name(value):
    value = " ".join(str(value).split())
    value = value.removesuffix("(통합)").strip()
    return "세종시" if value == "세종특별자치시" else value


def districts(data_dir):
    features = load_boundaries(data_dir / "processed" / "sigungu.geojson")["features"]
    return pd.DataFrame([{key: feature["properties"][key] for key in ("adm_cd", "sido", "sigungu")}
                         for feature in features])


def read_population(path, year, areas):
    header = ["mois", "name", "age_code", "age_text", "month", "total", "male", "female"]
    raw = pd.read_csv(path, encoding="cp949", skiprows=3, names=header, dtype=str)
    raw = raw[raw["month"].eq(f"{year}{POPULATION_MONTH:02d}")].copy()
    if raw.empty:
        raise ValueError(f"{path.name}: {POPULATION_MONTH}월 자료가 없습니다.")
    raw["mois"] = raw["mois"].str.strip("'")
    names = raw[["mois", "name"]].drop_duplicates().set_index("mois")["name"].str.strip()
    if not names.index.is_unique:
        raise ValueError(f"{path.name}: 같은 지역코드에 복수 명칭이 있습니다.")
    names = names.to_dict()
    lookup = {(row.sido, area_name(row.sigungu)): row.adm_cd for row in areas.itertuples()}
    crosswalk = {}
    for code, name in names.items():
        if len(code) != 5:
            continue
        parent = area_name(names.get(code[:-1] + "0", ""))
        if code[-1] != "0" and parent and parent.endswith("시") and not name.startswith(parent):
            name = f"{parent} {name}"
        province = PROVINCE_NAMES.get(names.get(code[:2]))
        matched = lookup.get((province, area_name(name)))
        if matched:
            crosswalk[code] = matched
    duplicates = {code for code, count in Counter(crosswalk.values()).items() if count > 1}
    crosswalk = {code: matched for code, matched in crosswalk.items() if matched not in duplicates}

    raw["age"] = pd.to_numeric(raw["age_text"].str.extract(r"^(\d+)")[0], errors="coerce")
    province_codes = {code for code in names if len(code) == 2}
    raw = raw[raw["age"].between(19, 100) & raw["mois"].isin(province_codes | crosswalk.keys())]
    long = raw.melt(id_vars=["mois", "age"], value_vars=["male", "female"], var_name="sex", value_name="count")
    long["count"] = pd.to_numeric(long["count"], errors="coerce")
    long["sex"] = long["sex"].map(dict(zip(("male", "female"), SEXES.values(), strict=True)))
    long["age_band"] = age_band(long["age"])
    complete = long.groupby("mois").agg(rows=("count", "size"), valid=("count", "count"))
    good = complete.index[complete["rows"].eq(164) & complete["valid"].eq(164)]
    long = long[long["mois"].isin(good) & ~long.duplicated(["mois", "age", "sex"], keep=False)]
    long = long.groupby("mois").filter(lambda rows: len(rows) == 164)
    long["adm_cd"] = long["mois"].map(crosswalk).fillna(long["mois"])
    by_age = long.groupby(["adm_cd", "sex", "age_band"], as_index=False)["count"].sum()
    long["older"] = long["count"].where(long["age"].ge(65), 0)
    sizes = long.groupby("adm_cd").agg(adults=("count", "sum"), older=("older", "sum"))
    sizes["older"] = 100 * sizes["older"] / sizes["adults"]
    provinces = {c: PROVINCE_NAMES[n] for c, n in names.items() if len(c) == 2 and n in PROVINCE_NAMES}
    provincial = by_age[by_age["adm_cd"].isin(provinces)].copy()
    provincial["sido"] = provincial["adm_cd"].map(provinces)
    return by_age, sizes, provincial, crosswalk


def estimate(value):
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(\*+)?\s*(?:\((\d+(?:\.\d+)?)\))?\s*(\*+)?", str(value).strip())
    if not match:
        return None, None, None
    rate, before, stderr, after = match.groups()
    return float(rate), float(stderr) if stderr else None, before or after


def official_district_rates(path, areas, data_dir):
    official = pd.read_excel(path, sheet_name="DATA", usecols=[
        "name_kor", "city_semi", "SIGNGU_NM",
        *[f"{prefix}{str(year)[-2:]}" for year in (2023, 2024, 2025)
          for prefix in ("n_", "me", "s_me")],
    ])
    official["metric"] = official["name_kor"].map({"현재흡연율": "cigarette", "담배제품 현재사용률": "tobacco"})
    official["sido"] = official["city_semi"].map(PROVINCE_NAMES)
    official["sigungu"] = official["SIGNGU_NM"].map(area_name)
    matched = official.dropna(subset=["sido"]).merge(areas, on=["sido", "sigungu"])
    existing = load_rates(data_dir / "processed" / "tobacco_rates.csv")
    published = existing[existing["level"].eq("sigungu")].set_index(["year", "adm_cd"])["rate"]
    rows = []
    for metric, years in METRIC_YEARS.items():
        subset = matched[matched["metric"].eq(metric)]
        for year in years:
            suffix = str(year)[-2:]
            candidates = []
            for record in subset.to_dict("records"):
                crude, se, flag = estimate(record[f"me{suffix}"])
                std, _, std_flag = estimate(record[f"s_me{suffix}"])
                if crude is None and std is None:
                    continue
                n = pd.to_numeric(str(record[f"n_{suffix}"]).replace(",", ""), errors="coerce")
                candidates.append(dict(adm_cd=record["adm_cd"], sido=record["sido"], metric=metric,
                                       year=year, crude=crude, se=se, flag=flag, std=std,
                                       std_flag=std_flag, n=n))
            frame = pd.DataFrame(candidates)
            if frame.empty:
                continue
            frame = frame[~frame.duplicated("adm_cd", keep=False)].copy()
            if metric == "tobacco":
                reused = frame["adm_cd"].map(published.get(year, pd.Series(dtype=float)))
                # The map and appendix DATA sheet are independent extractions.
                comparable = frame["std"].notna() & reused.notna()
                if (frame.loc[comparable, "std"].sub(reused[comparable]).abs() > 0.11).any():
                    raise ValueError(f"{year}년 공식 담배제품 표준화율이 지도 입력과 불일치합니다.")
                frame["std"] = reused.combine_first(frame["std"])
            rows.append(frame)
    indicators = []
    for year in (2023, 2024, 2025):
        by_year = matched.assign(factor=matched["name_kor"].map(HEALTH_FACTORS)).dropna(subset=["factor"])
        by_year = by_year[~by_year.duplicated(["adm_cd", "factor"], keep=False)].copy()
        estimates = by_year[f"s_me{str(year)[-2:]}"].map(estimate)
        by_year["value"] = estimates.map(lambda item: item[0] if item[2] is None else None)
        table = by_year.pivot(index="adm_cd", columns="factor", values="value").reset_index()
        indicators.append(table.assign(year=year))
    return pd.concat(rows, ignore_index=True), pd.concat(indicators, ignore_index=True)


def official_province_rates(path):
    records = []
    age_labels = dict(zip(("19-29", "30-39", "40-49", "50-59", "60-69", "70이상"), AGE_BANDS, strict=True))
    with pd.ExcelFile(path) as book:
        sheets = {"1.": "cigarette", "3.": "tobacco", **PROVINCE_HEALTH_SHEETS}
        for prefix, metric in sheets.items():
            sheet = next(name for name in book.sheet_names if name.startswith(prefix))
            table = book.parse(sheet, header=None)
            years = {year: table.iloc[11].tolist().index(year) for year in METRIC_YEARS.get(metric, (2023, 2024, 2025))}
            province = None
            for row in table.itertuples(index=False, name=None):
                province = PROVINCE_NAMES.get(str(row[2]).strip(), province)
                age = age_labels.get(str(row[3]).strip())
                kind = str(row[4]).strip()
                if province and metric == "cigarette" and str(row[3]).strip() == "N":
                    for year, index in years.items():
                        n = pd.to_numeric(str(row[index]).replace(",", ""), errors="coerce")
                        if pd.notna(n):
                            records.append(dict(metric=metric, year=year, sido=province, rate_type="n", rate=int(n)))
                    continue
                if prefix in PROVINCE_HEALTH_SHEETS and kind != "(표준화율)":
                    continue
                if not province or not (age or kind in {"(조율)", "(표준화율)"}):
                    continue
                for year, index in years.items():
                    rate, se, flag = estimate(row[index])
                    records.append(dict(metric=metric, year=year, sido=province, age_band=age,
                                        rate_type="age" if age else "std" if "표준화율" in kind else "crude",
                                        rate=rate, se=se, flag=flag))
    return pd.DataFrame(records)


def read_regional_db(path, areas):
    lookup = areas.set_index(["sido", "sigungu"])["adm_cd"].to_dict()
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    records, aggregates, inventory = [], [], {}
    try:
        for name in workbook.sheetnames:
            sheet = workbook[name]
            inventory[name] = {"rows": sheet.max_row, "columns": sheet.max_column}
            if name not in {"2023", "2024", "2025"}:
                continue
            iterator = sheet.values
            ids, headers = next(iterator), next(iterator)
            columns = {key: headers.index(label) for key, label in DB_FACTORS.items() if label in headers}
            inventory[name]["used_columns"] = {key: {"label": headers[i], "id": ids[i]} for key, i in columns.items()}
            matched = []
            for row in iterator:
                province = PROVINCE_NAMES.get(row[2])
                code = lookup.get((province, area_name(row[3])))
                if row[2] == row[3] == "전국":
                    aggregates.append({"area": "전국", "year": int(name), **{key: row[index] for key, index in columns.items()}})
                elif province and PROVINCE_NAMES.get(row[3]) == province:
                    aggregates.append({"area": province, "year": int(name), **{key: row[index] for key, index in columns.items()}})
                if code:
                    matched.append({"adm_cd": code, "year": int(name),
                                    **{key: row[index] for key, index in columns.items()}})
            names = Counter(row["adm_cd"] for row in matched)
            records.extend(row for row in matched if names[row["adm_cd"]] == 1)
            inventory[name]["matched_unique"] = sum(count == 1 for count in names.values())
    finally:
        workbook.close()
    return pd.DataFrame(records), pd.DataFrame(aggregates), inventory


def read_retail_snapshot(path, areas):
    columns = ["개방자치단체코드", "관리번호", "영업상태명", "도로명주소", "지번주소", "최종수정시점", "데이터갱신시점"]
    permits = pd.read_csv(path, encoding="cp949", usecols=columns, dtype=str)
    n_rows = len(permits)
    permits = permits.dropna(subset=["개방자치단체코드", "관리번호"])
    permits = permits.sort_values("최종수정시점", na_position="first", kind="stable").drop_duplicates(columns[:2], keep="last")
    active = permits[permits["영업상태명"].str.strip().eq("영업/정상")].copy()
    lookup = {(row.sido, area_name(row.sigungu)): row.adm_cd for row in areas.itertuples()}
    # The current snapshot uses this combined address prefix. The 2025
    # analysis uses the previous SGIS boundaries under two separate labels.
    combined = {"전남광주통합특별시": ("광주광역시", "전라남도")}

    def from_address(address):
        words = str(address).split(maxsplit=3)
        if len(words) < 2:
            return None
        province = PROVINCE_NAMES.get(words[0])
        if province == "세종특별자치시":
            return lookup.get((province, "세종시"))
        candidates = combined.get(words[0], (province,))
        matched = {match for name in candidates if
                   (match := lookup.get((name, " ".join(words[1:3]))) or lookup.get((name, words[1])))}
        return next(iter(matched)) if len(matched) == 1 else None

    road = active["도로명주소"].map(from_address)
    lot = active["지번주소"].map(from_address)
    agree = road.isna() | lot.isna() | road.eq(lot)
    codes = road.combine_first(lot).where(agree)
    province_by_code = areas.set_index("adm_cd")["sido"]
    road_province = road.map(province_by_code).combine_first(active["도로명주소"].str.split().str[0].map(PROVINCE_NAMES))
    lot_province = lot.map(province_by_code).combine_first(active["지번주소"].str.split().str[0].map(PROVINCE_NAMES))
    province_agreement = road_province.isna() | lot_province.isna() | road_province.eq(lot_province)
    provinces = road_province.combine_first(lot_province).where(province_agreement)
    dates = pd.to_datetime(permits["데이터갱신시점"], format="mixed", errors="coerce").dropna()
    return codes.value_counts().to_dict(), {
        "rows": n_rows, "active_permits": len(active), "matched_active": int(codes.notna().sum()),
        "conflicting_address_rows": int((~agree).sum()),
        "province_counts": provinces.value_counts().to_dict(),
        "matched_province": int(provinces.notna().sum()),
        "latest_row_update": dates.max().date().isoformat() if not dates.empty else None,
        "snapshot_date": None, "population_year": 2025,
    }
