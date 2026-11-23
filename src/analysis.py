"""Descriptive Seoul district analysis using data already present in data/."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .data_loader import ROOT, load_rates


HEALTH_VARIABLES = {
    "담배제품 현재사용자의 금연시도율": "현재사용자의 금연 시도율",
    "담배제품 현재 미사용자의 직장실내 간접흡연 노출률": "비사용자의 직장 실내 간접흡연 노출률",
    "월간음주율": "월간 음주율",
    "고위험음주율": "고위험 음주율",
    "걷기 실천율": "걷기 실천율",
    "중강도 이상 신체활동 실천율": "중강도 이상 신체활동 실천율",
    "비만율(자가보고)_비만": "비만율(자가보고)",
    "스트레스 인지율": "스트레스 인지율",
    "연간 우울감 경험률": "연간 우울감 경험률",
}


def parse_estimate(value):
    """Parse official estimate strings such as '15.4(1.3)' into estimate/SE."""
    if pd.isna(value):
        return np.nan, np.nan
    matches = re.findall(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not matches:
        return np.nan, np.nan
    estimate = float(matches[0])
    stderr = float(matches[1]) if len(matches) > 1 else np.nan
    return estimate, stderr


def load_seoul_health_indicators(data_dir: Path | str = ROOT / "data") -> pd.DataFrame:
    """Read 2025 standardized health behavior estimates for Seoul's districts."""
    data_dir = Path(data_dir)
    files = sorted(data_dir.glob("2025년_3-2*.xlsx"))
    if not files:
        raise FileNotFoundError("2025 시·군·구 건강행태 통계 엑셀 파일을 찾지 못했습니다.")
    frame = pd.read_excel(files[0], sheet_name="DATA")
    required = {"name_kor", "city_semi", "SIGNGU_NM", "s_me25"}
    if not required.issubset(frame.columns):
        raise ValueError(f"건강행태 통계에 필수 컬럼이 없습니다: {sorted(required - set(frame.columns))}")

    frame = frame[(frame["city_semi"] == "서울") & frame["name_kor"].isin(HEALTH_VARIABLES)].copy()
    parsed = frame["s_me25"].map(parse_estimate)
    frame["value"] = parsed.map(lambda pair: pair[0])
    frame["std_error"] = parsed.map(lambda pair: pair[1])
    frame["factor"] = frame["name_kor"].map(HEALTH_VARIABLES)
    frame = frame.rename(columns={"SIGNGU_NM": "sigungu", "n_25": "sample_n"})
    frame["year"] = 2025
    result = frame[["year", "sigungu", "factor", "value", "std_error", "sample_n"]]
    return result.dropna(subset=["sigungu", "factor", "value"]).drop_duplicates(["sigungu", "factor"])


def load_active_retailer_counts(data_dir: Path | str = ROOT / "data") -> pd.DataFrame:
    """Count active tobacco retailers by Seoul district from the local CSV."""
    candidates = list(Path(data_dir).glob("*담배소매업*.csv"))
    if not candidates:
        raise FileNotFoundError("담배소매업 CSV를 data 폴더에서 찾지 못했습니다.")
    columns = ["관리번호", "영업상태명", "도로명주소", "지번주소", "최종수정시점"]
    frame = pd.read_csv(
        candidates[0],
        encoding="cp949",
        usecols=columns,
        dtype={column: "string" for column in columns},
        low_memory=False,
    )
    # One permit number represents one outlet. Remove repeated rows before counting.
    frame = frame.sort_values("최종수정시점", na_position="first").drop_duplicates("관리번호", keep="last")
    active = frame[frame["영업상태명"].str.strip().eq("영업/정상")].copy()
    address = active["도로명주소"].fillna("").str.strip()
    address = address.mask(address.eq(""), active["지번주소"].fillna("").str.strip())
    active["sigungu"] = address.str.extract(r"^(?:서울특별시|서울)\s+([가-힣]+구)(?:\s|$)", expand=False)
    counts = active.dropna(subset=["sigungu"]).groupby("sigungu").size().rename("retailer_count").reset_index()
    return counts


def load_seoul_population(data_dir: Path | str = ROOT / "data") -> pd.DataFrame:
    """Read 2024 SGIS total population at five-digit district-code level."""
    candidates = list(Path(data_dir).rglob("*총인구*.csv"))
    if not candidates:
        raise FileNotFoundError("SGIS 총인구 CSV를 찾지 못했습니다.")
    frame = pd.read_csv(
        candidates[0],
        encoding="cp949",
        usecols=["행정구역코드", "통계항목", "통계값"],
        dtype={"행정구역코드": "string", "통계항목": "string"},
    )
    frame["행정구역코드"] = frame["행정구역코드"].str.zfill(5)
    frame = frame[(frame["통계항목"] == "to_in_001") & frame["행정구역코드"].str.fullmatch(r"11\d{3}")]
    return frame.rename(columns={"행정구역코드": "adm_cd", "통계값": "population"})[["adm_cd", "population"]]


def build_seoul_analysis(
    rates: pd.DataFrame,
    indicators: pd.DataFrame,
    retailer_counts: pd.DataFrame,
    population: pd.DataFrame,
    selected_code: str,
    year: int = 2025,
) -> dict:
    """Build peer comparisons and descriptive Spearman associations for Seoul."""
    districts = rates[(rates["year"] == year) & (rates["level"] == "sigungu") & (rates["sido"] == "서울특별시")].copy()
    districts["adm_cd"] = districts["adm_cd"].astype(str)
    districts["rate"] = pd.to_numeric(districts["rate"], errors="coerce")
    districts = districts.dropna(subset=["rate"]).drop_duplicates("adm_cd")
    if districts.empty:
        raise ValueError(f"{year}년 서울 시·군·구 흡연율 자료가 없습니다.")
    selected_rows = districts[districts["adm_cd"] == str(selected_code)]
    if selected_rows.empty:
        raise ValueError("선택한 지역의 흡연율 자료를 찾지 못했습니다.")
    selected = selected_rows.iloc[0]

    peer_median = float(districts["rate"].median())
    quartile_low, quartile_high = districts["rate"].quantile([0.25, 0.75]).tolist()
    if selected.rate <= quartile_low:
        band = "서울 내 낮은 편"
    elif selected.rate >= quartile_high:
        band = "서울 내 높은 편"
    else:
        band = "서울 내 중간 범위"
    # Rank 1 means the highest observed district rate.
    rank = int(districts["rate"].rank(method="min", ascending=False).loc[selected_rows.index[0]])

    health = indicators.pivot(index="sigungu", columns="factor", values="value")
    peer = districts.merge(health, left_on="sigungu", right_index=True, how="left")
    retailer_counts = retailer_counts.copy()
    if not retailer_counts.empty:
        peer = peer.merge(retailer_counts, on="sigungu", how="left")
    else:
        peer["retailer_count"] = np.nan
    population = population.copy()
    population["adm_cd"] = population["adm_cd"].astype(str).str.zfill(5)
    peer = peer.merge(population, on="adm_cd", how="left")
    peer["retailers_per_10k"] = peer["retailer_count"] / peer["population"] * 10_000

    selected_data = peer[peer["adm_cd"] == str(selected_code)]
    if selected_data.empty:
        raise ValueError("선택한 지역의 분석용 변수를 매칭하지 못했습니다.")
    selected_data = selected_data.iloc[0]

    factor_rows = []
    for factor in [*HEALTH_VARIABLES.values(), "retailers_per_10k"]:
        if factor not in peer:
            continue
        values = pd.to_numeric(peer[factor], errors="coerce")
        valid = peer[["rate", factor]].dropna()
        # Rank correlation without scipy: ranks followed by Pearson correlation.
        rho = (
            valid["rate"].rank(method="average").corr(valid[factor].rank(method="average"))
            if len(valid) >= 3
            else np.nan
        )
        value = selected_data.get(factor)
        median = values.median()
        if pd.isna(value) or pd.isna(median):
            continue
        factor_rows.append(
            {
                "변수": "담배소매점(인구 1만 명당)" if factor == "retailers_per_10k" else factor,
                "단위": "개소" if factor == "retailers_per_10k" else "%",
                "선택 지역": float(value),
                "서울 구 중앙값": float(median),
                "서울 중앙값과 차이": float(value - median),
                "흡연율과의 Spearman ρ": float(rho) if pd.notna(rho) else np.nan,
                "비교 구 수": int(len(valid)),
            }
        )
    factor_table = pd.DataFrame(factor_rows)
    if not factor_table.empty:
        factor_table["절대 연관계수"] = factor_table["흡연율과의 Spearman ρ"].abs()
        factor_table = factor_table.sort_values("절대 연관계수", ascending=False).drop(columns="절대 연관계수")

    return {
        "district": str(selected["sigungu"]),
        "rate": float(selected["rate"]),
        "peer_median": peer_median,
        "difference": float(selected["rate"] - peer_median),
        "rank": rank,
        "district_count": int(len(districts)),
        "band": band,
        "factors": factor_table,
        "peer_data": peer,
        "year": int(year),
    }
