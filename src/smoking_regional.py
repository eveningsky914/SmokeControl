"""Regional associations using same-year official standardized rates."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from scipy.stats import spearmanr

from .smoking_inputs import FACTORS


MIN_REGIONS = 40
MODEL_FACTORS = ("low_income", "older", "doctors", "high_risk_drinking", "manufacturing",
                 "stress", "parks", "depression", "employment", "unemployment")


def regional_comparisons(factors, areas, province_rates, db_totals, retail):
    """Compare like-for-like regional indicators, even without a local smoking rate."""
    comparisons = {}
    for year, rows in factors.groupby("year"):
        year = int(year)
        districts = areas.merge(rows[["adm_cd", *FACTORS]], on="adm_cd", validate="one_to_one")
        population = rows.dropna(subset=["area"]).set_index("area")
        totals = db_totals.get(year, {})
        health = province_rates[
            province_rates["year"].eq(year) & province_rates["rate_type"].eq("std")
            & province_rates["metric"].isin(FACTORS) & province_rates["flag"].isna()
        ].dropna(subset=["rate"])
        health_by_area = {name: group.set_index("metric")["rate"].to_dict() for name, group in health.groupby("sido")}

        baselines = {}
        for name, group in [("전국", districts), *districts.groupby("sido")]:
            values = {}
            for factor in FACTORS:
                available = group[factor].dropna()
                if not available.empty:
                    values[factor] = {"value": float(available.median()), "kind": "median", "districts": len(available)}
            official = {**totals.get(name, {}), **health_by_area.get(name, {})}
            for factor, value in official.items():
                if factor != "manufacturing" and pd.notna(value):
                    values[factor] = {"value": value, "kind": "official"}

            if name in population.index:
                resident = population.loc[name]
                adults = resident["adults"]
                if pd.notna(resident["older"]):
                    values["older"] = {"value": resident["older"], "kind": "population"}
                if pd.notna(adults) and adults > 0:
                    manufacturing = official.get("manufacturing")
                    if pd.notna(manufacturing):
                        values["manufacturing"] = {"value": manufacturing / adults * 1_000, "kind": "calculated"}
                    if year == 2025 and retail:
                        count = retail["active_permits"] if name == "전국" else retail["province_counts"].get(name)
                        if count is not None:
                            kind = "calculated" if name == "전국" else "matched_addresses"
                            values["retail"] = {"value": count / adults * 10_000, "kind": kind}
            baselines[name] = values
        comparisons[str(year)] = {
            "districts": districts.set_index("adm_cd")[list(FACTORS)].to_dict("index"),
            "baselines": baselines,
        }
    return comparisons


def spatial_residuals(residual, codes, points):
    if len(residual) < 6 or any(code not in points for code in codes):
        return None
    locations = np.deg2rad(np.array([points[code] for code in codes]))
    lon, lat = locations.T
    unit = np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    distance = cdist(unit, unit)
    np.fill_diagonal(distance, np.inf)
    neighbors = np.argsort(distance, axis=1, kind="stable")[:, :4]
    centered = residual - residual.mean()
    denom = centered @ centered
    if denom <= 0:
        return None

    def moran(values):
        return float(values @ values[neighbors].mean(axis=1) / denom)

    observed = moran(centered)
    rng = np.random.default_rng(2025)
    shuffled = np.array([moran(rng.permutation(centered)) for _ in range(199)])
    return {"moran_i": observed, "upper_tail_p": float((1 + (shuffled >= observed).sum()) / 200)}


def model(peer, points):
    available = [key for key in MODEL_FACTORS if peer[key].count() >= 0.65 * len(peer)]
    selected = []
    for key in available:
        if len(selected) == 5:
            break
        trial = [*selected, key]
        complete = peer.dropna(subset=trial)
        if len(complete) < max(MIN_REGIONS, 0.6 * len(peer)) or (complete[trial].std() <= 0).any():
            continue
        corr = np.atleast_2d(complete[trial].corr().to_numpy())
        if np.linalg.cond(corr) > 1e5 or np.diag(np.linalg.inv(corr)).max() > 5:
            continue
        selected = trial
    if len(selected) < 3:
        return None
    complete = peer.dropna(subset=selected)
    predictors = complete[selected]
    predictors = (predictors - predictors.mean()) / predictors.std(ddof=0)
    x = np.column_stack([np.ones(len(complete)), predictors])
    y = complete["std"].to_numpy()
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y - x @ beta
    leverage = np.einsum("ij,jk,ik->i", x, np.linalg.inv(x.T @ x), x)
    mse = residual @ residual / (len(y) - len(beta))
    if mse <= 0 or np.ptp(y) == 0:
        return None
    cooks = residual ** 2 * leverage / (len(beta) * mse * (1 - leverage) ** 2)
    influential = cooks > 4 / len(y)
    trimmed = ~influential
    reduced = np.linalg.lstsq(x[trimmed], y[trimmed], rcond=None)[0] if trimmed.sum() >= MIN_REGIONS else None
    provinces = complete["sido"].to_numpy()
    leave_one_out = np.array([
        np.linalg.lstsq(x[provinces != province], y[provinces != province], rcond=None)[0]
        for province in np.unique(provinces) if (provinces != province).sum() >= MIN_REGIONS
    ])
    vifs = np.diag(np.linalg.inv(predictors.corr().to_numpy()))
    terms = {}
    for i, (key, vif) in enumerate(zip(selected, vifs, strict=True), 1):
        stable_province = bool(len(leave_one_out) and (np.sign(leave_one_out[:, i]) == np.sign(beta[i])).all())
        stable_outliers = bool(reduced is not None and np.sign(reduced[i]) == np.sign(beta[i]))
        terms[key] = dict(beta=float(beta[i]), vif=float(vif), stable_province=stable_province,
                          stable_outliers=stable_outliers)
    return {"n": len(complete), "r_squared": float(1 - residual @ residual / ((y - y.mean()) @ (y - y.mean()))),
            "terms": terms, "influential_n": int(influential.sum()),
            "spatial": spatial_residuals(residual, complete["adm_cd"], points)}


def regional_factors(official, factors, points):
    all_results = {}
    for (year, metric), rows in official.groupby(["year", "metric"]):
        peer = rows.merge(factors[factors["year"].eq(year)], on="adm_cd", how="left", validate="one_to_one")
        peer = peer.dropna(subset=["std"])
        peer = peer[peer["std_flag"].isna() & peer["n"].ge(30)]
        stats = {}
        for key in FACTORS:
            valid = peer.dropna(subset=[key])
            if key == "retail" and year != 2025:
                continue
            rho = None
            if len(valid) >= MIN_REGIONS and valid[key].nunique() > 1 and valid["std"].nunique() > 1:
                rho = float(spearmanr(valid[key], valid["std"]).statistic)
            stats[key] = ({"n": len(valid), "eligible": len(peer), "rho": rho,
                           "median": float(valid[key].median()), "lower": float(valid[key].quantile(0.25)),
                           "upper": float(valid[key].quantile(0.75))}
                          if not valid.empty else {"n": 0, "eligible": len(peer), "rho": None})
        all_results.setdefault(metric, {})[str(year)] = {
            "stats": stats, "model": model(peer, points),
            "districts": peer[["adm_cd", *FACTORS]].set_index("adm_cd").to_dict("index"),
        }
    for metric_results in all_results.values():
        for result in metric_results.values():
            for key, stats in result["stats"].items():
                stats["annual_rho"] = {
                    year: row["stats"][key]["rho"] for year, row in metric_results.items()
                    if key != "retail" and key in row["stats"] and row["stats"][key]["rho"] is not None
                }
    return all_results


def priority_factors(result, district, gap):
    """Require a local outlying value and mutually supporting regional evidence."""
    if result is None or not result["model"] or not gap:
        return []
    values = result["districts"].get(district, {})
    ranked = []
    for key, term in result["model"]["terms"].items():
        entry = result["stats"][key]
        value, rho = values.get(key), entry["rho"]
        trend = list(entry["annual_rho"].values())
        if value is None or rho is None or abs(rho) < 0.15 or len(trend) < 2:
            continue
        if not term["stable_province"] or not term["stable_outliers"] or abs(term["beta"]) < 0.2:
            continue
        if np.sign(rho) != np.sign(term["beta"]) or any(np.sign(rho) != np.sign(other) for other in trend):
            continue
        distance = value - entry["median"]
        if entry["lower"] <= value <= entry["upper"] or distance * rho * gap <= 0:
            continue
        ranked.append((abs(term["beta"]) * abs(rho) * entry["n"] / entry["eligible"], key))
    return [key for _, key in sorted(ranked, reverse=True)[:5]]
