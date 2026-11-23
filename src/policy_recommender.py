"""Rank policy options from aggregate analysis using explicit, local rules."""

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from .analysis import HEALTH_VARIABLES


MIN_COMPARISON_DISTRICTS = 20
PRIORITY_GAP_PP = 2.0
QUIT_ATTEMPTS = HEALTH_VARIABLES["담배제품 현재사용자의 금연시도율"]
WORKPLACE_EXPOSURE = HEALTH_VARIABLES["담배제품 현재 미사용자의 직장실내 간접흡연 노출률"]
RETAILERS = "담배소매점(인구 1만 명당)"


@dataclass(frozen=True)
class Indicator:
    value: float
    median: float
    district_count: int

    @property
    def gap(self) -> float:
        return round(self.value - self.median, 8)


@dataclass(frozen=True)
class PolicyContext:
    district: str
    year: int
    tobacco_use: Indicator
    band: str
    quit_attempts: Indicator | None = None
    workplace_exposure: Indicator | None = None
    retailers: Indicator | None = None

    @classmethod
    def from_analysis(cls, analysis: dict) -> "PolicyContext":
        indicators = {}
        for row in analysis["factors"].to_dict("records"):
            value, median = row["선택 지역"], row["서울 구 중앙값"]
            if isfinite(value) and isfinite(median):
                indicators[row["변수"]] = Indicator(value, median, row["비교 구 수"])
        return cls(
            district=analysis["district"],
            year=analysis["year"],
            tobacco_use=Indicator(analysis["rate"], analysis["peer_median"], analysis["district_count"]),
            band=analysis["band"],
            quit_attempts=indicators.get(QUIT_ATTEMPTS),
            workplace_exposure=indicators.get(WORKPLACE_EXPOSURE),
            retailers=indicators.get(RETAILERS),
        )


@dataclass(frozen=True)
class Recommendation:
    policy_id: str
    priority: int
    reason: str


class PolicyRecommender(Protocol):
    def __call__(self, context: PolicyContext, /) -> tuple[Recommendation, ...]: ...


def _compare(label: str, indicator: Indicator | None) -> str:
    if indicator is None:
        return f"{label} 비교 자료를 확보하면 이 사업의 우선순위를 검토할 수 있습니다."
    return (
        f"{label} {indicator.value:.1f}%, 서울 자치구 중앙값 {indicator.median:.1f}% "
        f"(차이 {indicator.gap:+.1f}%p, 비교 {indicator.district_count}개 구)입니다."
    )


def _has_coverage(indicator: Indicator | None) -> bool:
    return indicator is not None and indicator.district_count >= MIN_COMPARISON_DISTRICTS


def recommend_policies(context: PolicyContext) -> tuple[Recommendation, ...]:
    """Return options in local priority order, with comparable inputs on each card."""
    tobacco = context.tobacco_use
    high_use = _has_coverage(tobacco) and context.band == "서울 내 높은 편" and tobacco.gap > 0
    quit_attempts = context.quit_attempts
    exposure = context.workplace_exposure
    low_attempts = quit_attempts is not None and _has_coverage(quit_attempts) and quit_attempts.gap <= -PRIORITY_GAP_PP
    high_exposure = exposure is not None and _has_coverage(exposure) and exposure.gap >= PRIORITY_GAP_PP

    tobacco_reason = _compare("담배제품 현재사용률", tobacco)
    recommendations = (
        Recommendation(
            "clinic",
            2 if high_use else 1,
            tobacco_reason + (
                " 서울 내 높은 구간으로 기존 금연클리닉의 참여와 후속 상담 확대를 우선 검토합니다."
                if high_use else " 주민이 상시 이용할 수 있는 기본 금연지원 사업입니다."
            ),
        ),
        Recommendation(
            "campaign",
            3 if low_attempts else 0,
            _compare(QUIT_ATTEMPTS, quit_attempts) + (
                " 금연을 시도할 계기와 이용 경로를 함께 안내하는 사업을 우선 검토합니다."
                if low_attempts else ""
            ),
        ),
        Recommendation(
            "smoke_free",
            3 if high_exposure else 0,
            _compare(WORKPLACE_EXPOSURE, exposure) + (
                " 직장 실내 노출 감소를 우선 검토합니다."
                if high_exposure else ""
            ),
        ),
        Recommendation(
            "outreach",
            2 if high_use else 0,
            tobacco_reason + (
                " 사용률이 서울 내 높은 구간입니다. 상담을 이용하기 어려운 집단이 있는지 확인해 방문과 전화 지원을 검토합니다."
                if high_use else " 방문 상담은 기관별 참여 수요와 서비스 접근성을 확인해 검토합니다."
            ),
        ),
    )
    return tuple(sorted(recommendations, key=lambda item: -item.priority))
