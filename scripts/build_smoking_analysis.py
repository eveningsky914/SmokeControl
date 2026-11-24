"""Build the nationwide analysis artifact from the local official inputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data_loader import load_boundaries
from src.smoking_comparison import AGE_BANDS, METRIC_YEARS, MIN_CELL_COUNT, SEXES, compare_composition, weighted_rates
from src.smoking_inputs import (
    FACTORS, POPULATION_MONTH, districts, official_district_rates, official_province_rates,
    read_population, read_regional_db, read_retail_snapshot, source_file,
)
from src.smoking_regional import regional_comparisons, regional_factors
from src.smoking_survey import SUMMARY_PATH, logistic, read_survey, summaries, survey_coverage


YEARS = (2023, 2024, 2025)
OFFICIAL_MEDIANS = {"cigarette": {2023: 20.3, 2024: 18.9, 2025: 17.9}, "tobacco": {2024: 22.6, 2025: 22.1}}
PUBLISHED_SURVEY_N = {2023: 231752, 2024: 231728, 2025: 231615}
GUIDES = "https://chronic.kdca.go.kr/chs/mnl/mnlBoardMain.do"


def records(frame):
    return frame.to_dict("records")


def age_reference(official, province_pop, national_pop):
    if national_pop.empty:
        return None
    province_rates = official[official["rate_type"].eq("age") & official["flag"].isna()]
    province_count = province_pop.groupby(["sido", "age_band"], as_index=False)["count"].sum()
    if len(province_count) != 17 * len(AGE_BANDS) or len(province_rates) != len(province_count):
        return None
    joined = province_count.merge(province_rates, on=["sido", "age_band"], validate="one_to_one")
    if len(joined) != len(province_count) or joined["rate"].isna().any():
        return None
    joined["weighted"] = joined["rate"] * joined["count"]
    by_age = joined.groupby("age_band", as_index=False).agg(count=("count", "sum"), weighted=("weighted", "sum"))
    by_age["rate"] = by_age["weighted"] / by_age["count"]
    national_count = national_pop.groupby("age_band", as_index=False)["count"].sum().rename(columns={"count": "reference_count"})
    baseline = by_age.merge(national_count, on="age_band", validate="one_to_one")
    if len(baseline) != len(AGE_BANDS) or not baseline["reference_count"].eq(baseline["count"]).all():
        return None
    return baseline[["age_band", "rate", "reference_count"]]


def survey_reference(sample, comparison, population, official):
    # A district only contributes if its survey file contains the same
    # official matched sample and reproduces its published crude estimate.
    observed = weighted_rates(sample, ["adm_cd"])
    checks = observed.merge(official[["adm_cd", "crude", "n"]], on="adm_cd",
                            suffixes=("_raw", "_official"), validate="one_to_one")
    checks["delta"] = checks["rate"] - checks["crude"]
    comparable = checks["n_raw"].sub(checks["n_official"]).abs().le(3) & checks["delta"].abs().le(0.35)
    audit = {"paired_districts": len(checks), "validated_districts": int(comparable.sum()),
             "median_absolute_delta_pp": float(checks["delta"].abs().median()) if len(checks) else None,
             "unvalidated_paired_codes": sorted(checks.loc[~comparable, "adm_cd"])}
    validated = set(checks.loc[comparable, "adm_cd"])
    areas = validated.intersection(population["adm_cd"].unique())
    reference_sample = sample[sample["adm_cd"].isin(areas)]
    cells = weighted_rates(reference_sample, ["sex", "age_band"])
    if comparison.empty or len(cells) != len(AGE_BANDS) * len(SEXES) or (cells["n"] < MIN_CELL_COUNT).any():
        return None, audit, validated
    counts = (population[population["adm_cd"].isin(areas)].groupby(["sex", "age_band"], as_index=False)["count"]
              .sum().rename(columns={"count": "reference_count"}))
    if len(counts) != len(cells):
        return None, audit, validated
    audit.update(districts=len(areas), adults=int(counts["reference_count"].sum()),
                 adult_share=float(counts["reference_count"].sum() / comparison["count"].sum()))
    return cells[["sex", "age_band", "n", "rate"]].merge(counts, on=["sex", "age_band"]), audit, validated


def build_year(data_dir, year, areas, official, provinces, log):
    population_path = data_dir / f"population{year}.csv"
    try:
        population, sizes, province_pop, crosswalk = read_population(population_path, year, areas)
    except (FileNotFoundError, ValueError) as error:
        log["warnings"].append(f"{year} 주민등록인구: {error}")
        population = pd.DataFrame(columns=["adm_cd", "sex", "age_band", "count"])
        sizes = pd.DataFrame(columns=["adults", "older"], index=pd.Index([], name="adm_cd"))
        province_pop, crosswalk = pd.DataFrame(), {}
    national_pop = population[population["adm_cd"].eq("00")]
    if len(national_pop) != len(AGE_BANDS) * len(SEXES):
        log["warnings"].append(f"{year} 주민등록인구: 전국 성인 성·연령 구간 누락")
        national_pop = national_pop.iloc[:0]
    audit = {"file": population_path.name, "month": POPULATION_MONTH, "matched": len(sizes.index.intersection(areas.adm_cd)),
             "eligible": len(areas), "national_adults": int(national_pop["count"].sum()),
             "unmatched": sorted(set(areas.adm_cd) - set(sizes.index))}
    log["population"][str(year)] = audit
    print(f"{year} 인구: {audit['matched']}/{audit['eligible']}개 경계", flush=True)

    raw_path = data_dir / "importantRawData" / f"chs{str(year)[-2:]}_all.csv"
    survey = None
    try:
        survey, columns, survey_audit = read_survey(raw_path, year, crosswalk)
        survey["sido"] = survey["adm_cd"].map(areas.set_index("adm_cd")["sido"])
        published = provinces[provinces["year"].eq(year) & provinces["rate_type"].eq("n")]
        coverage = survey_coverage(survey, published.set_index("sido")["rate"].to_dict(), PUBLISHED_SURVEY_N[year])
        log["survey"][str(year)] = {"file": raw_path.name, **survey_audit, "columns": columns,
                                    "official_n": PUBLISHED_SURVEY_N[year], "coverage": coverage, "metrics": {}}
        print(f"{year} 원시자료: {len(survey):,}행, {survey_audit['matched_districts']}개 지역", flush=True)
    except (FileNotFoundError, ValueError) as error:
        log["warnings"].append(f"{year} 원시자료: {error}")
        print(log["warnings"][-1], flush=True)

    all_results = {}
    district_population = {code: group[["sex", "age_band", "count"]]
                           for code, group in population.groupby("adm_cd") if len(code) == 5}
    for metric, years in METRIC_YEARS.items():
        if year not in years:
            continue
        selected = official[official["year"].eq(year) & official["metric"].eq(metric)].set_index("adm_cd")
        province = provinces[provinces["year"].eq(year) & provinces["metric"].eq(metric)]
        national_ref = age_reference(province, province_pop, national_pop)
        partial_ref, individual_rows, fitted, ref_audit = None, [], None, None
        if survey is not None and metric in survey:
            sample = survey.rename(columns={metric: "smoking"}).dropna(subset=["smoking", "weight", "sex", "age_band"])
            partial_ref, ref_audit, validated = survey_reference(sample, national_pop, population, selected.reset_index())
            individual = summaries(sample)
            individual_rows = records(individual[~individual["scope"].eq("district") | individual["adm_cd"].isin(validated)])
            fitted = logistic(sample)
            log["survey"][str(year)]["metrics"][metric] = {
                "valid_rows": len(sample), "matched_rows": int(sample["adm_cd"].notna().sum()), "validation": ref_audit,
            }
        log["official"].setdefault(str(year), {})[metric] = {
            "districts": len(selected), "age_reference": national_ref is not None,
        }
        districts_for_metric = {}
        for code, groups in district_population.items():
            statistics = selected.loc[code].to_dict() if code in selected.index else {}
            crude = statistics.get("crude")
            reliable = (crude is not None and pd.notna(crude) and statistics.get("n", 0) >= MIN_CELL_COUNT
                        and (statistics.get("flag") or "") != "**")
            actual = float(crude) if reliable else None
            ages = groups.groupby("age_band", as_index=False)["count"].sum()
            comparison = compare_composition(ages, national_ref, actual, ["age_band"]) if national_ref is not None else None
            by_sex = compare_composition(groups, partial_ref, actual, ["sex", "age_band"]) if partial_ref is not None else None
            districts_for_metric[code] = {"national_age": comparison, "sample_sex_age": by_sex}
        all_results[metric] = {
            "official": selected[["crude", "se", "flag", "n", "std", "std_flag"]].to_dict("index"),
            "province": province[province["rate_type"].eq("std")].set_index("sido")["rate"].to_dict(),
            "official_national_median": OFFICIAL_MEDIANS[metric][year],
            "population": {code: records(groups) for code, groups in district_population.items()},
            "population_national": records(national_pop[["sex", "age_band", "count"]]),
            "comparison": districts_for_metric, "sample_reference": ref_audit,
            "individual": individual_rows, "logistic": fitted,
        }
    aggregate_areas = {"00": "전국"}
    if not province_pop.empty:
        aggregate_areas.update(province_pop.set_index("adm_cd")["sido"].to_dict())
    sizes = sizes.reset_index()
    return all_results, sizes.assign(year=year, area=sizes["adm_cd"].map(aggregate_areas))


def build(data_dir):
    areas = districts(data_dir)
    district_book = source_file(data_dir, "2025*3-2*건강행태.xlsx")
    province_book = source_file(data_dir, "2025*3-1*건강행태.xlsx")
    official, health = official_district_rates(district_book, areas, data_dir)
    provinces = official_province_rates(province_book)
    log = {"survey_guides": GUIDES, "survey": {}, "population": {}, "official": {}, "warnings": [],
           "official_sources": [district_book.name, province_book.name, "processed/tobacco_rates.csv", "processed/sigungu.geojson"]}
    results, populations = {}, []
    for year in YEARS:
        year_data, sizes = build_year(data_dir, year, areas, official, provinces, log)
        populations.append(sizes)
        for metric, result in year_data.items():
            results.setdefault(metric, {})[str(year)] = result
    common = set.intersection(*(set(log["survey"].get(str(year), {}).get("columns", [])) for year in YEARS))
    log["survey_common_columns"] = sorted(common)
    for survey in log["survey"].values():
        survey["columns_outside_three_year_intersection"] = sorted(set(survey["columns"]) - common)
        survey["match_fraction"] = survey["matched_rows"] / survey["rows"] if survey["rows"] else None

    factors = pd.concat(populations, ignore_index=True)
    db_totals = {}
    try:
        db_path = source_file(data_dir, "*건강 결정요인 DB*.xlsx")
        regional_db, aggregates, inventory = read_regional_db(db_path, areas)
        factors = factors.merge(regional_db, on=["adm_cd", "year"], how="outer", validate="one_to_one")
        factors["manufacturing"] = pd.to_numeric(factors["manufacturing"], errors="coerce") / factors["adults"] * 1_000
        log["regional_db"] = {"file": db_path.name, "sheets": inventory}
        if not aggregates.empty:
            aggregates = aggregates.drop_duplicates(["year", "area"], keep=False)
            columns = list(aggregates.columns.difference(["year", "area"], sort=False))
            aggregates[columns] = aggregates[columns].apply(pd.to_numeric, errors="coerce")
            db_totals = {int(year): rows.set_index("area")[columns].to_dict("index") for year, rows in aggregates.groupby("year")}
    except (FileNotFoundError, ValueError, KeyError) as error:
        log["warnings"].append(f"지역 결정요인 DB: {error}")
    retail = None
    try:
        retail_path = source_file(data_dir, "*담배소매업*.csv")
        counts, retail = read_retail_snapshot(retail_path, areas)
        active = factors["adm_cd"].map(counts).where(factors["year"].eq(2025))
        factors["retail"] = active / factors["adults"] * 10_000
        log["retail"] = {"file": retail_path.name, **retail, "district_counts": counts}
    except (FileNotFoundError, ValueError) as error:
        log["warnings"].append(f"담배소매점: {error}")
    factors = factors.merge(health, on=["adm_cd", "year"], how="outer", validate="one_to_one")
    for key in FACTORS:
        factors[key] = pd.to_numeric(factors[key], errors="coerce") if key in factors else np.nan
    features = load_boundaries(data_dir / "processed" / "sigungu.geojson")["features"]
    points = {f["properties"]["adm_cd"]: f["properties"]["label_point"] for f in features
              if "label_point" in f["properties"]}
    regional = regional_factors(official, factors, points)
    comparisons = regional_comparisons(factors, areas, provinces, db_totals, retail)
    return {"schema": 1, "metadata": log, "results": results, "regional": regional,
            "region_comparisons": comparisons, "areas": areas.set_index("adm_cd")[["sido", "sigungu"]].to_dict("index")}


def json_ready(value):
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    return None if value is pd.NA or (isinstance(value, float) and not np.isfinite(value)) else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    data_dir = parser.parse_args().data_dir
    result = json_ready(build(data_dir))
    output = data_dir / "processed" / SUMMARY_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    file = NamedTemporaryFile(mode="w", encoding="utf-8", dir=output.parent, delete=False)
    temporary = Path(file.name)
    try:
        with file:
            json.dump(result, file, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    print(output, flush=True)


if __name__ == "__main__":
    main()
