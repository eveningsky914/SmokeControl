"""Curated policy options, implementation examples, and official sources."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class Policy:
    title: str
    evidence: str
    international_sources: tuple[Source, ...]
    local_example: str
    local_source: Source
    action: str
    measure: str
    local_evaluation: Source | None = None


WHO_CESSATION = Source(
    "WHO 성인 금연치료 지침",
    "https://www.who.int/publications/i/item/9789240096431",
)
QUITLINE = Source(
    "미국 CPSTF 금연상담전화 근거 검토",
    "https://thecommunityguide.cdc.gov/findings/tobacco-use-quitline-interventions.html",
)

POLICIES = {
    "clinic": Policy(
        title="보건소 금연클리닉 등록과 후속 상담 강화",
        evidence="WHO는 성인 담배 사용자의 금연을 지원하기 위해 행동 상담과 필요한 경우 의료진을 통한 약물치료를 권고합니다.",
        international_sources=(WHO_CESSATION,),
        local_example="서울시 25개 자치구 보건소는 금연클리닉을 운영합니다.",
        local_source=Source("서울시 흡연자 금연지원 서비스", "https://news.seoul.go.kr/welfare/archives/243201"),
        action="보건소·지역 의원의 상담 안내를 정리하고, 참여자와 첫 상담 및 후속 상담 일정을 예약합니다.",
        measure="신규 등록자 수, 후속 상담 완료율, 추적조사 응답률과 6개월 금연 유지율을 기록합니다.",
        local_evaluation=Source("국내 보건소 금연클리닉 6개월 성과 평가", "https://pubmed.ncbi.nlm.nih.gov/22752272/"),
    ),
    "campaign": Policy(
        title="금연 상담으로 연결되는 지역 캠페인",
        evidence="미국 CPSTF는 충분한 도달 범위를 갖춘 금연 캠페인이 금연과 상담전화 이용을 늘린다는 근거를 확인했습니다. 주된 근거는 TV 중심 캠페인에서 나왔습니다.",
        international_sources=(
            Source(
                "미국 CPSTF 금연 커뮤니케이션 근거 검토",
                "https://thecommunityguide.cdc.gov/findings/tobacco-use-mass-reach-health-communication-interventions.html",
            ),
            Source("미국 CDC Tips 캠페인 평가", "https://www.cdc.gov/pcd/issues/2020/20_0052.htm"),
        ),
        local_example="국가금연지원서비스에서 보건소 금연클리닉과 금연상담전화를 안내합니다.",
        local_source=Source(
            "금연두드림 국가금연지원서비스 안내",
            "https://nosmk.khepi.or.kr/nsk/user/extra/ntcc/105/announce/oftenQuestion/jsp/LayOutPage.do?category=0300000000&categoryVal=03",
        ),
        action="동주민센터·구청 채널에서 금연지원 안내를 반복 노출하고, 보건소 예약이나 상담전화로 연결합니다.",
        measure="채널별 도달 수, 상담 신청 건수와 실제 등록 건수를 집계합니다.",
    ),
    "smoke_free": Policy(
        title="직장 실내 금연 관리와 간접흡연 노출 감소",
        evidence="미국 CPSTF는 실내 금연정책이 간접흡연 노출을 줄인다는 강한 근거를 확인했습니다.",
        international_sources=(
            Source(
                "미국 CPSTF 금연구역 정책 근거 검토",
                "https://thecommunityguide.cdc.gov/findings/tobacco-use-smoke-free-policies.html",
            ),
        ),
        local_example="국내 보건소는 지역 금연구역 지정·관리와 금연 교육을 수행합니다.",
        local_source=Source("금연두드림 전국 보건소 사업 안내", "https://nosmk.khepi.or.kr/nsk/ntcc/subIndex/267.do"),
        action="관할 사업장과 금연표지·신고 안내를 점검합니다. 점검 장소를 정할 때는 현장 확인을 거치고, 적용 범위는 관할 법령과 조례를 확인합니다.",
        measure="점검 시설 수, 시정 완료율, 비사용자의 직장 실내 간접흡연 노출률 추이를 확인합니다.",
    ),
    "outreach": Policy(
        title="찾아가는 금연상담과 전화 후속 지원",
        evidence="미국 CPSTF는 금연을 원하는 사람에게 상담원이 후속 전화를 제공하는 방식이 금연 성공을 높인다는 근거를 확인했습니다.",
        international_sources=(QUITLINE,),
        local_example="서울 강서구는 관내 사업장·아파트·복지관 등을 방문하는 이동 금연클리닉을 안내합니다.",
        local_source=Source(
            "서울시 강서구 이동 금연클리닉 사례",
            "https://youth.seoul.go.kr/infoData/sprtInfo/view.do?key=2309130006&sprtInfoId=66828",
        ),
        action="기관별 참여 수요와 상담 인력을 확인해 방문 상담을 시범 운영하고, 희망자에게 전화 후속 상담을 연결합니다.",
        measure="방문 상담 참여자 수, 전화 후속 상담 연결률, 상담 유지율을 기록합니다.",
        local_evaluation=Source("국내 후속 전화 금연상담 단기 평가", "https://pubmed.ncbi.nlm.nih.gov/18955799/"),
    ),
}
