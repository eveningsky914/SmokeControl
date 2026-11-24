"""Age composition comparisons for crude adult smoking prevalence."""

from __future__ import annotations

import numpy as np
import pandas as pd


AGE_BANDS = ["19–29세", "30–39세", "40–49세", "50–59세", "60–69세", "70세 이상"]
SEXES = {1: "남성", 2: "여성"}
MIN_CELL_COUNT = 30
METRICS = {"cigarette": "일반담배 현재흡연율", "tobacco": "담배제품 현재사용률"}
METRIC_YEARS = {"cigarette": (2023, 2024, 2025), "tobacco": (2024, 2025)}


def age_band(age: pd.Series) -> pd.Series:
    return pd.cut(age, [18, 29, 39, 49, 59, 69, np.inf], labels=AGE_BANDS).astype("string")


def weighted_rates(frame: pd.DataFrame, groups: list[str]) -> pd.DataFrame:
    """Estimate percentages among valid respondents using individual weights."""
    valid = frame.dropna(subset=[*groups, "smoking", "weight"])
    valid = valid.loc[valid["weight"].gt(0)].assign(weighted=valid["weight"] * valid["smoking"])
    totals = valid.groupby(groups, observed=True).agg(
        n=("smoking", "size"), events=("smoking", "sum"),
        weight=("weight", "sum"), weighted=("weighted", "sum"),
    )
    totals["rate"] = 100 * totals["weighted"] / totals["weight"]
    return totals.reset_index()


def compare_composition(population, reference, actual, groups):
    """Decompose actual − reference into composition and remaining differences.

    Population tables supply person counts, not survey weights. Every reference
    stratum must have a rate and both populations must cover the same strata.
    """
    if population.empty or reference.empty or population["count"].isna().any():
        return None
    cells = reference.merge(population, on=groups, how="outer", validate="one_to_one", indicator=True)
    if not cells["_merge"].eq("both").all():
        return None
    required = cells[["rate", "reference_count", "count"]]
    if not np.isfinite(required.to_numpy(dtype=float)).all().item():
        return None
    if not cells["rate"].between(0, 100).all() or (cells[["reference_count", "count"]] < 0).any().any():
        return None
    if cells["count"].sum() <= 0 or cells["reference_count"].sum() <= 0:
        return None
    cells["share"] = cells["count"] / cells["count"].sum()
    cells["reference_share"] = cells["reference_count"] / cells["reference_count"].sum()
    baseline = float(cells["reference_share"] @ cells["rate"])
    expected = float(cells["share"] @ cells["rate"])
    # Centering on the baseline preserves the sum and makes high-rate strata
    # with above-reference population shares positive contributors.
    cells["contribution"] = (cells["share"] - cells["reference_share"]) * (cells["rate"] - baseline)
    return {
        "actual": actual,
        "expected": expected,
        "reference": baseline,
        "gap": None if actual is None else actual - baseline,
        "composition": expected - baseline,
        "remaining": None if actual is None else actual - expected,
        "cells": cells.drop(columns="_merge").to_dict("records"),
    }
