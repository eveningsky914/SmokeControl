"""KDCA CHS responses and exploratory survey-weighted individual associations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import t

from .smoking_comparison import AGE_BANDS, MIN_CELL_COUNT, SEXES, age_band, weighted_rates


FACTORS = {
    "sex": "성별", "age_band": "연령대", "work": "최근 1주일 경제활동", "occupation": "직업군",
    "income": "월 환산 가구소득", "assistance": "기초생활보장 수급 여부", "drinking": "지난 1년 음주 빈도",
    "high_risk": "고위험 음주", "stress": "스트레스 인지", "depression": "지난 1년 우울감 경험",
}
REFERENCE = {
    "sex": "여성", "age_band": "19–29세", "job_group": "사무직", "income": "400만 원 이상",
    "assistance": "현재 미수급", "drinking": "지난 1년 미음주", "stress": "낮음", "depression": "없음",
}
BASE_COLUMNS = [
    "EXAMIN_YEAR", "age", "sex", "CTPRVN_CODE", "PBHLTH_CODE", "SPOT_NO", "signgu_code",
    "kstrata", "wt_p", "smf_01z1", "sma_01z1", "sma_03z2", "soa_01z1", "soa_06z2",
    "fma_04z1", "fma_12z1", "fma_13z1", "fma_14z1", "dra_01z1", "drb_01z3",
    "drb_03z1", "mta_01z1", "mtb_01z1",
]
PRODUCT_COLUMNS = ["sma_36z1", "sma_37z1", "sma_08z1", "sma_11z2", "sma_12z2"]
SUMMARY_PATH = "national_smoking_analysis.json"


def outcomes(raw, year):
    lifetime, current = raw["sma_01z1"], raw["sma_03z2"]
    screened = raw["smf_01z1"]
    times = {1: 1, 2: 1, 3: 0}
    cigarette = current.map(times).where(lifetime.eq(2))
    if year == 2023:
        cigarette = cigarette.mask(lifetime.isin([1, 3, 8]), 0)
        return {"cigarette": cigarette}
    cigarette = cigarette.mask(lifetime.isin([1, 3]), 0).where(screened.eq(1)).mask(screened.eq(2), 0)
    heated = raw["sma_37z1"].map(times).where(raw["sma_36z1"].eq(1)).mask(raw["sma_36z1"].eq(2), 0)
    days = raw["sma_11z2"]
    liquid = days.between(1, 31).astype(float).where(days.between(0, 31) & raw["sma_08z1"].eq(1))
    liquid = liquid.mask(raw["sma_08z1"].eq(2), 0)
    other = raw["sma_12z2"].map({1: 1, 2: 0, 3: 0})
    components = pd.concat([cigarette, heated, liquid, other], axis=1)
    components = components.where(screened.eq(1), axis=0).mask(screened.eq(2), 0, axis=0)
    # Both years have the four component questions and the 2025 appendix
    # publishes the comparable historical indicator including other tobacco.
    product = components.max(axis=1, skipna=False)
    return {"cigarette": cigarette, "tobacco": product}


def read_survey(path, year, crosswalk):
    header = pd.read_csv(path, nrows=0).columns.tolist()
    columns = BASE_COLUMNS + (PRODUCT_COLUMNS if year >= 2024 else [])
    missing = set(columns) - set(header)
    missing_product = missing.intersection(PRODUCT_COLUMNS)
    if missing - missing_product:
        raise ValueError(f"{path.name}: 검증된 변수 누락 {sorted(missing - missing_product)}")
    raw = pd.read_csv(path, usecols=[name for name in columns if name in header],
                      dtype={name: str for name in ("signgu_code", "CTPRVN_CODE", "PBHLTH_CODE", "SPOT_NO", "kstrata")})
    for name in missing_product:
        raw[name] = np.nan
    if not raw["EXAMIN_YEAR"].eq(year).all():
        raise ValueError(f"{path.name}: 조사연도 불일치")
    # Province-only code changes in the survey. Join to the same-year
    # resident-registration codes, then to the exact mapped SGIS district.
    stable_codes = {"42": "51", "45": "52"}
    code = raw["signgu_code"].str.strip()
    normalized = code.str[:2].map(stable_codes) + code.str[2:]
    adm_cd = code.map(crosswalk).combine_first(normalized.map(crosswalk))
    sex = raw["sex"]
    frequency = raw["drb_01z3"].where(raw["dra_01z1"].eq(1)).mask(raw["dra_01z1"].eq(2), 1)
    amount = raw["drb_03z1"]
    frequent = frequency.isin([5, 6])
    high_risk = (frequent & ((sex.eq(1) & amount.ge(4)) | (sex.eq(2) & amount.ge(3))))
    high_risk = high_risk.map({True: "해당", False: "해당 없음"}).where(
        frequency.isin(range(1, 7)) & (~frequent | (sex.isin(SEXES) & amount.isin(range(1, 6))))
    )
    annual = raw["fma_13z1"].where(raw["fma_12z1"].eq(1) & raw["fma_13z1"].between(0, 30_000)) / 12
    monthly = raw["fma_14z1"].where(raw["fma_12z1"].eq(2) & raw["fma_14z1"].between(0, 2_500))
    monthly = annual.combine_first(monthly)
    occupation = raw["soa_06z2"].where(raw["soa_01z1"].eq(1))
    work = raw["soa_01z1"]
    occupation_names = ("관리직", "전문직", "사무직", "서비스직", "판매직", "농림어업",
                        "기능직", "기계조작·조립", "단순노무", "직업군인")
    model_occupations = {1: "관리·전문직", 2: "관리·전문직", 3: "사무직", 4: "서비스·판매직", 5: "서비스·판매직",
                         **dict.fromkeys(range(6, 11), "생산·현장 직군")}
    frame = pd.DataFrame({
        "adm_cd": adm_cd, "sex": sex.map(SEXES), "age_band": age_band(raw["age"]),
        "weight": raw["wt_p"].where(raw["wt_p"].gt(0) & np.isfinite(raw["wt_p"])),
        "stratum": raw["CTPRVN_CODE"] + ":" + raw["PBHLTH_CODE"] + ":" + raw["kstrata"],
        "psu": raw["SPOT_NO"], "work": work.map({1: "경제활동", 2: "경제활동 안 함"}),
        "occupation": occupation.map(dict(enumerate(occupation_names, 1))),
        "job_group": occupation.map(model_occupations).mask(work.eq(2), "경제활동 안 함"),
        "income": pd.cut(monthly, [-1, 200, 400, np.inf], right=False,
                         labels=["200만 원 미만", "200만~400만 원 미만", "400만 원 이상"]).astype("string"),
        "assistance": raw["fma_04z1"].map({1: "현재 수급", 2: "현재 미수급", 3: "현재 미수급"}),
        "drinking": frequency.map({1: "지난 1년 미음주", 2: "월 1회 미만", 3: "월 1회", 4: "월 2~4회",
                                   5: "주 2~3회", 6: "주 4회 이상"}),
        "high_risk": high_risk,
        "stress": raw["mta_01z1"].map({1: "높음", 2: "높음", 3: "낮음", 4: "낮음"}),
        "depression": raw["mtb_01z1"].map({1: "있음", 2: "없음"}),
        **outcomes(raw, year),
    })
    if missing_product:
        frame = frame.drop(columns="tobacco")
    audit = {
        "rows": len(raw), "source_districts": int(code.nunique()), "matched_districts": int(adm_cd.nunique()),
        "matched_rows": int(adm_cd.notna().sum()), "missing_design_rows": int(frame[["weight", "stratum", "psu"]].isna().any(axis=1).sum()),
        "factor_valid_rows": {name: int(frame[name].notna().sum()) for name in FACTORS},
        "unmatched_codes": sorted(code[adm_cd.isna()].dropna().unique()), "missing_product_columns": sorted(missing_product),
    }
    return frame, header, audit


def summaries(frame):
    tables = []
    for factor in FACTORS:
        for scope, groups in (("sample", [factor]), ("province", ["sido", factor]), ("district", ["adm_cd", factor])):
            rates = weighted_rates(frame, groups).rename(columns={factor: "category"})
            rates = rates[rates["n"].ge(MIN_CELL_COUNT) & rates["events"].ge(5) & rates["n"].sub(rates["events"]).ge(5)]
            tables.append(rates.assign(factor=factor, scope=scope))
    return pd.concat(tables, ignore_index=True)[["adm_cd", "sido", "scope", "factor", "category", "rate", "n"]]


def survey_coverage(survey, published, official_n):
    counts = survey["sido"].value_counts()
    provinces = {name: {"provided_n": int(counts.get(name, 0)), "official_n": int(expected),
                        "complete": counts.get(name, 0) == expected}
                 for name, expected in published.items() if expected > 0}
    national = {"provided_n": len(survey), "official_n": official_n,
                "complete": len(survey) == official_n and sum(published.values()) == official_n
                and all(item["complete"] for item in provinces.values())}
    return {"national": national, "provinces": provinces}


def logistic(frame):
    """Fit a weighted logit with Taylor linearized PSU covariance within strata."""
    # Job status encodes employment with occupation, avoiding a redundant
    # employment predictor. Drinking frequency enters without its derived flag.
    columns = ["smoking", "weight", "stratum", "psu", *REFERENCE]
    valid = frame.dropna(subset=columns)
    if len(valid) < 500:
        return None
    indicators, terms = [], []
    for factor, baseline in REFERENCE.items():
        counts = valid.groupby(factor)["smoking"].agg(["size", "sum"])
        if counts.empty or baseline not in counts.index or (counts["size"] < MIN_CELL_COUNT).any():
            return None
        if (counts["sum"] < 5).any() or (counts["size"] - counts["sum"] < 5).any():
            return None
        for category in sorted(counts.index):
            if category == baseline:
                continue
            indicators.append(valid[factor].eq(category).to_numpy(dtype=float))
            terms.append((factor, category, baseline))
    x = np.column_stack([np.ones(len(valid)), *indicators])
    y = valid["smoking"].to_numpy()
    weight = valid["weight"].to_numpy()
    weight = weight / weight.mean()

    def objective(beta):
        linear = x @ beta
        return np.dot(weight, np.logaddexp(0, linear) - y * linear), x.T @ (weight * (expit(linear) - y))

    fit = minimize(objective, np.zeros(x.shape[1]), jac=True, method="L-BFGS-B",
                   options={"gtol": 1e-6, "ftol": 1e-12})
    if not fit.success:
        return None
    probability = expit(x @ fit.x)
    hessian = x.T @ ((weight * probability * (1 - probability))[:, None] * x)
    if not np.isfinite(hessian).all() or np.linalg.cond(hessian) > 1e10:
        return None
    score = pd.DataFrame(x * (weight * (y - probability))[:, None])
    score["stratum"] = valid["stratum"].to_numpy()
    score["psu"] = valid["psu"].to_numpy()
    psu_scores = score.groupby(["stratum", "psu"]).sum()
    by_stratum = psu_scores.groupby(level="stratum")
    m = by_stratum[0].transform("size")
    multi = m.gt(1)
    centered = (psu_scores - by_stratum.transform("mean")).loc[multi].to_numpy()
    scaled = centered * np.sqrt(m[multi].to_numpy() / (m[multi].to_numpy() - 1))[:, None]
    strata = int(psu_scores.index.get_level_values("stratum").nunique())
    dof = len(psu_scores) - strata
    if dof < 2:
        return None
    inverse = np.linalg.inv(hessian)
    covariance = inverse @ (scaled.T @ scaled) @ inverse
    se = np.sqrt(np.maximum(np.diag(covariance), 0))
    limit = t.ppf(0.975, dof) * se
    rows = [dict(factor=factor, category=category, baseline=baseline, odds_ratio=float(np.exp(beta)),
                 low=float(np.exp(beta - margin)), high=float(np.exp(beta + margin)))
            for (factor, category, baseline), beta, margin in zip(terms, fit.x[1:], limit[1:], strict=True)]
    return {"n": len(valid), "strata": strata, "psus": len(psu_scores), "dof": dof,
            "singleton_strata": int((~multi).sum()), "terms": rows}
