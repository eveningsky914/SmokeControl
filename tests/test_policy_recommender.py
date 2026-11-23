import pandas as pd

from src.policy_catalog import POLICIES
from src.policy_recommender import QUIT_ATTEMPTS, WORKPLACE_EXPOSURE, PolicyContext, recommend_policies


def district_context(rate=24.0, band="서울 내 높은 편", factors=()):
    return PolicyContext.from_analysis(
        {
            "district": "강북구",
            "year": 2025,
            "rate": rate,
            "peer_median": 19.7,
            "district_count": 25,
            "band": band,
            "factors": pd.DataFrame(factors),
        }
    )


def factor(name, value, median, count=25):
    return {"변수": name, "선택 지역": value, "서울 구 중앙값": median, "비교 구 수": count}


def test_policy_priority_uses_local_indicators_and_preserves_sources():
    context = district_context(
        factors=(factor(QUIT_ATTEMPTS, 40.9, 42.9), factor(WORKPLACE_EXPOSURE, 9.0, 7.0))
    )
    recommendations = recommend_policies(context)

    assert [(item.policy_id, item.priority) for item in recommendations] == [
        ("campaign", 3), ("smoke_free", 3), ("clinic", 2), ("outreach", 2)
    ]
    assert "40.9%" in recommendations[0].reason
    assert set(POLICIES) == {item.policy_id for item in recommendations}
    for policy in POLICIES.values():
        assert policy.local_source.url.startswith("https://")
        assert policy.international_sources


def test_missing_or_sparse_indicators_leave_candidates_without_priority():
    context = district_context(
        rate=15.4,
        band="서울 내 낮은 편",
        factors=(factor(QUIT_ATTEMPTS, 30.0, 42.9, count=19),),
    )
    recommendations = recommend_policies(context)

    assert recommendations[0].policy_id == "clinic"
    assert recommendations[0].priority == 1
    assert all(item.priority == 0 for item in recommendations[1:])
    assert "비교 자료를 확보" in next(item.reason for item in recommendations if item.policy_id == "smoke_free")
