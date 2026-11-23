"""Streamlit views for nationwide smoking factors and regional differences."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from .data_loader import ROOT
from .smoking_comparison import AGE_BANDS, METRICS
from .smoking_inputs import FACTORS as REGION_FACTORS
from .smoking_regional import priority_factors
from .smoking_survey import FACTORS as SURVEY_FACTORS, SUMMARY_PATH


ARTIFACT = ROOT / "data" / "processed" / SUMMARY_PATH
BASELINES = {"national_age": "전국 조사 · 나이대별", "sample_sex_age": "제공 표본 · 성별과 나이대별"}
COMPARISON_RATE_HELP = "지역에 따라 주민의 나이 구성이 다릅니다. 같은 나이 구성을 적용한 질병관리청 수치로 비교합니다."
RATE_DIFFERENCE_HELP = "두 비율의 차이입니다. 예를 들어 20%와 23%는 3%p 차이입니다."
UNAVAILABLE = "자료 없음"


@st.cache_resource(show_spinner=False, max_entries=1)
def load_analysis_artifact(path, modified_ns):
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if data.get("schema") != 1:
        raise ValueError("지원되는 분석 자료 버전을 찾지 못했습니다.")
    return data


def pct(value):
    return UNAVAILABLE if value is None else f"{value:.1f}%"


def pp(value):
    return UNAVAILABLE if value is None else f"{value:+.1f}%p"


def direction(value):
    return f"{abs(value):.1f}%p {'높습니다' if value > 0 else '낮습니다'}"


def official_summary(report, official, province, rate_name):
    st.header("다른 지역과 비교하면")
    comparison = st.radio("어느 지역과 비교할까요?", ["전국 시·군·구의 가운데 값", "우리 지역이 속한 시·도"], horizontal=True,
                          key="analysis_official_comparator")
    use_national = comparison.startswith("전국")
    baseline = report["official_national_median"] if use_national else report["province"].get(province)
    rate = official.get("std")
    columns = st.columns(3)
    columns[0].metric(f"지역 비교용 {rate_name}", pct(rate))
    columns[1].metric(comparison, pct(baseline))
    gap = rate - baseline if rate is not None and baseline is not None else None
    columns[2].metric("우리 지역과의 차이", pp(gap), help=RATE_DIFFERENCE_HELP)
    st.caption(COMPARISON_RATE_HELP)
    if use_national:
        st.caption("전국의 가운데 값은 시·군·구 수치를 순서대로 놓았을 때 가운데에 오는 값입니다.")
    if official.get("std_flag"):
        st.warning("질병관리청이 이 지역 수치를 해석할 때 주의가 필요하다고 표시했습니다.")


def population_table(report, code):
    population = pd.DataFrame(report["population"].get(code, []))
    if population.empty or not report["population_national"]:
        return
    national = pd.DataFrame(report["population_national"]).rename(columns={"count": "national"})
    population = population.merge(national, on=["sex", "age_band"])
    population["share"] = 100 * population["count"] / population["count"].sum()
    population["national"] = 100 * population["national"] / population["national"].sum()
    population = population.sort_values(["sex", "age_band"])
    with st.expander("우리 지역에는 어떤 나이대가 많나요?"):
        columns = st.columns(2)
        for column, (sex, cells) in zip(columns, population.groupby("sex"), strict=True):
            with column:
                st.caption(f"{sex} · 전체 성인 중 비중")
                chart = cells.set_index("age_band")[["share", "national"]].reindex(AGE_BANDS)
                st.bar_chart(chart.rename(columns={"share": "우리 지역", "national": "전국"}), stack=False, height=210)
        population = population.rename(columns={"sex": "성별", "age_band": "연령", "count": "성인 수",
                                                 "share": "우리 지역 비중(%)", "national": "전국 비중(%)"})
        st.dataframe(population.round(2), hide_index=True)


def composition_view(report, code, official, year, month, rate_name):
    st.header("실제 조사와 예상 비교")
    choices = report["comparison"].get(code, {})
    available = [key for key in BASELINES if choices.get(key)]
    if not available:
        st.info("이 해에는 예상 수치를 계산할 자료가 부족합니다.")
        population_table(report, code)
        return None, None
    reference = st.radio("예상 수치의 기준", available, format_func=BASELINES.get,
                         horizontal=True, key="analysis_composition_reference")
    comparison = choices[reference]
    columns = st.columns(3)
    columns[0].metric(f"실제 조사 {rate_name}", pct(comparison["actual"]))
    columns[1].metric(f"예상 {rate_name}", pct(comparison["expected"]))
    columns[2].metric("실제와 예상의 차이", pp(comparison["remaining"]), help=RATE_DIFFERENCE_HELP)
    if comparison["remaining"] is None:
        st.info("우리 지역의 공식 조사 결과를 확인할 수 없어 예상 수치만 표시합니다.")
    elif abs(comparison["remaining"]) < 0.05:
        st.write("실제 조사 결과와 예상 수치가 거의 같습니다.")
    else:
        st.write(f"실제 조사 결과는 예상보다 **{direction(comparison['remaining'])}**.")

    if reference == "national_age":
        st.caption(f"우리 지역의 각 나이대가 전국의 같은 나이대와 같은 {rate_name}을 보인다고 가정해 예상했습니다.")
    else:
        sample = report["sample_reference"]
        st.caption(f"우리 지역 주민이 성별과 나이대가 같은 제공 표본의 주민과 같은 {rate_name}을 보인다고 가정해 예상했습니다.")
    with st.expander("예상 수치는 어떻게 계산하나요?"):
        if reference == "national_age":
            st.write("전국 17개 시·도의 조사 결과와 인구수로 나이대별 평균을 구했습니다.")
            groups = "나이대별"
        else:
            st.write(f"공식 조사 결과와 대조한 제공 표본은 {sample['districts']}개 지역입니다. "
                     f"이 지역에 전국 성인의 {sample['adult_share']:.1%}가 살며, 우리 지역도 포함될 수 있습니다.")
            groups = "성별·나이대별"
        st.write(f"{year}년 {month}월 주민등록 자료에서 만 19세 이상 지역 주민의 {groups} 비중을 구해 비교 기준에 적용했습니다.")
        st.write(f"비교 기준은 **{pct(comparison['reference'])}**입니다. "
                 f"우리 지역 사람들의 구성만 반영하면 이 기준에서 **{pp(comparison['composition'])}** 달라집니다.")
        if comparison["gap"] is not None:
            st.write(f"실제 조사 결과는 비교 기준과 **{pp(comparison['gap'])}** 차이가 납니다.")
        if comparison["actual"] is not None and official.get("se") is not None:
            st.caption(f"공식 조사에 {official['n']:,.0f}명이 답했습니다. 표준오차 {official['se']:.1f}%p는 "
                       "조사를 반복할 때 결과가 흔들릴 수 있는 정도입니다. 예상 수치와 실제·예상의 차이는 오차 범위를 계산하지 않았습니다.")
    if comparison["actual"] is not None and official.get("flag"):
        st.warning("질병관리청이 실제 조사 수치를 읽을 때 주의가 필요하다고 표시했습니다.")
    cells = pd.DataFrame(comparison["cells"])
    cells["group"] = cells["age_band"] if "sex" not in cells else cells["sex"] + " " + cells["age_band"]
    upwards = cells.loc[cells["contribution"].idxmax()]
    downwards = cells.loc[cells["contribution"].idxmin()]
    changes = []
    if upwards.contribution >= 0.05:
        changes.append(f"**{upwards.group}** {pp(upwards.contribution)}")
    if downwards.contribution <= -0.05:
        changes.append(f"**{downwards.group}** {pp(downwards.contribution)}")
    if changes:
        st.write("예상 수치를 가장 많이 높이거나 낮춘 집단은 " + ", ".join(changes) + "입니다.")
    with st.expander("어느 집단에서 차이가 컸나요?"):
        st.bar_chart(cells.set_index("group")[["contribution"]].rename(columns={"contribution": "예상 수치에 더한 차이(%p)"}),
                     horizontal=True, height=max(210, 28 * len(cells)))
        st.caption("막대의 +는 예상 수치를 높인 만큼, −는 낮춘 만큼입니다. 모두 더하면 사람들의 구성 때문에 달라진 수치가 됩니다.")
        table = cells.assign(share=100 * cells["share"], reference_share=100 * cells["reference_share"])
        labels = {"group": "인구집단", "share": "우리 지역 인구 비중(%)", "reference_share": "비교 기준 인구 비중(%)",
                  "rate": f"비교 기준의 집단별 {rate_name}(%)", "contribution": "예상 수치에 더한 차이(%p)"}
        st.dataframe(table[list(labels)].rename(columns=labels).round(2), hide_index=True)
    population_table(report, code)
    st.caption("조사 오차나 이 화면에서 살펴보지 않은 요인도 실제와 예상의 차이에 영향을 줄 수 있습니다.")
    return reference, comparison


def individual_view(report, code, province, peer, survey, rate_name):
    st.header("사람들의 특성별 차이")
    if not report["individual"]:
        st.info("선택한 연도와 항목에서 사람들의 특성별로 비교할 자료가 없습니다.")
        return False
    st.caption(f"제공 표본은 전국 조사에 참여한 {survey['official_n']:,}명 가운데 이 분석에 제공된 {survey['rows']:,}명의 응답입니다.")
    sample = pd.DataFrame(report["individual"]).reindex(columns=["adm_cd", "sido", "scope", "factor", "category", "rate", "n"])
    factor = st.selectbox("개인 특성", list(SURVEY_FACTORS), format_func=SURVEY_FACTORS.get, key="analysis_person_factor")
    sample = sample[sample["factor"].eq(factor)]
    coverage = survey.get("coverage", {})
    national = coverage.get("national", {})
    province_coverage = coverage.get("provinces", {}).get(province, {})
    national_label = "전국 전체" if national.get("complete") else "전국 비교 · 제공 표본"
    province_label = f"{province} 전체" if province_coverage.get("complete") else f"{province} · 제공 표본"
    groups = {
        "우리 지역": sample[sample["adm_cd"].eq(code)],
        province_label: sample[sample["scope"].eq("province") & sample["sido"].eq(province)],
        national_label: sample[sample["scope"].eq("sample")],
    }
    if peer:
        peer_code, peer_label = peer
        groups[peer_label] = sample[sample["adm_cd"].eq(peer_code)]
    categories = sample["category"].drop_duplicates().tolist()
    if categories:
        rates = pd.DataFrame({label: group.set_index("category")["rate"] for label, group in groups.items()}).reindex(categories)
        if rates.notna().any().any():
            st.bar_chart(rates.rename_axis("비교 집단"), stack=False, height=230, y_label=f"{rate_name}(%)")
        table = pd.DataFrame({"비교 집단": categories})
        for label, group in groups.items():
            details = {row.category: f"{row.rate:.1f}% ({row.n:,}명)" for row in group.itertuples()}
            table[label] = [details.get(category, UNAVAILABLE) for category in categories]
        st.dataframe(table, hide_index=True)
        st.caption(f"각 칸은 같은 집단 안에서의 {rate_name}입니다. 괄호는 두 질문에 모두 답한 사람 수입니다.")
    else:
        st.info("비교 결과를 보여주기에 응답이 충분한 집단이 없습니다.")
    if province_coverage:
        st.caption(f"{province} 자료는 공식 조사 {province_coverage['official_n']:,}명 중 "
                   f"{province_coverage['provided_n']:,}명의 응답을 담고 있습니다.")
    with st.expander("어떤 응답을 사용했나요?"):
        st.write("조사에 뽑힐 가능성과 주민 구성을 반영해 비율을 계산했습니다. 응답이 30명 이상이고 "
                 "사용한 사람과 사용하지 않은 사람이 각각 5명 이상인 집단을 표시합니다. "
                 "우리 지역 수치는 공식 조사 결과와 대조한 뒤 표시합니다.")
    result = report["logistic"]
    if result:
        with st.expander("다변량 로지스틱 회귀 · 제공 표본", expanded=False):
            st.caption("나이와 소득 등 다른 특성도 함께 고려한 뒤 각 집단을 기준 집단과 비교합니다. "
                       "오즈비가 1보다 크면 기준 집단보다 해당 행동을 할 경향이 높게 추정된 것입니다. "
                       "95% 신뢰구간에 1이 들어가면 어느 쪽이 높은지 뚜렷하지 않습니다.")
            st.caption(f"필요한 항목에 모두 답한 {result['n']:,}명의 자료로 분석했습니다. "
                       f"조사 설계의 층 {result['strata']:,}개와 집락 {result['psus']:,}개, 개인 가중치를 반영한 근사 신뢰구간입니다. "
                       f"집락이 하나뿐인 층 {result['singleton_strata']}개는 층 내 변동을 0으로 두었습니다.")
            terms = pd.DataFrame(result["terms"])
            terms["factor"] = terms["factor"].map({**SURVEY_FACTORS, "job_group": "직업군·경제활동"})
            terms["interpretation"] = terms.apply(
                lambda row: "기준 집단보다 높게 나타남" if row.low > 1 else
                "기준 집단보다 낮게 나타남" if row.high < 1 else "차이 방향이 뚜렷하지 않음", axis=1
            )
            st.dataframe(terms.rename(columns={"factor": "특성", "category": "비교 집단", "baseline": "기준 집단",
                                               "odds_ratio": "오즈비", "low": "95% 신뢰구간 하한", "high": "95% 신뢰구간 상한",
                                               "interpretation": "다른 특성도 고려한 결과"}).round(2), hide_index=True)
    else:
        st.info("선택한 연도와 항목의 다변량 로지스틱 회귀 결과를 표시할 만큼 자료가 충분하지 않습니다.")
    local = sample[sample["adm_cd"].eq(code) & sample["n"].ge(100)]
    pooled = sample[sample["scope"].eq("sample")][["category", "rate"]]
    contrast = local.merge(pooled, on="category", suffixes=("_local", "_sample"))
    if contrast.empty:
        return None
    return {"factor": factor, "contrasts": contrast.to_dict("records")}


def benchmark_text(benchmark):
    if benchmark is None:
        return UNAVAILABLE
    value = f"{benchmark['value']:,.2f}"
    kind = benchmark["kind"]
    if kind == "median":
        return f"{value} (가운데 값 · {benchmark['districts']}곳)"
    if kind == "matched_addresses":
        return f"{value} (주소 확인분)"
    return value


def regional_view(result, comparisons, code, province, peer, gap, retail, year, rate_name):
    st.header(f"지역 여건과 {rate_name}")
    if comparisons:
        districts = comparisons["districts"]
        baselines = comparisons["baselines"]
        local_values = districts.get(code, {})
        provincial_values = baselines.get(province, {})
        national_values = baselines.get("전국", {})
        peer_values = districts.get(peer[0], {}) if peer else {}
        comparison_rows = []
        for key, (name, unit, _) in REGION_FACTORS.items():
            if all(values.get(key) is None for values in (local_values, provincial_values, national_values, peer_values)):
                continue
            local_value = local_values.get(key)
            row = {"생활 여건": name, "단위": unit,
                   "우리 지역": f"{local_value:,.2f}" if local_value is not None else UNAVAILABLE,
                   province: benchmark_text(provincial_values.get(key)),
                   "전국": benchmark_text(national_values.get(key))}
            if peer:
                peer_value = peer_values.get(key)
                row[peer[1]] = f"{peer_value:,.2f}" if peer_value is not None else UNAVAILABLE
            comparison_rows.append(row)
        if comparison_rows:
            st.dataframe(pd.DataFrame(comparison_rows), hide_index=True)
            st.caption("‘가운데 값’은 전체 수치가 없을 때, 자료가 있는 시군구를 크기순으로 놓아 가운데에 오는 값입니다.")
    if not result:
        st.info("선택한 연도와 항목에서 지역 특성을 비교할 자료가 없습니다.")
        return []
    st.caption(f"지역마다 생활 여건이 다를 때, 지역 비교용 {rate_name}도 함께 달라지는지 살펴봤습니다.")
    values = result["districts"].get(code, {})
    priority = priority_factors(result, code, gap)
    if priority:
        st.markdown("**함께 살펴볼 지역 특성** · " + " · ".join(REGION_FACTORS[key][0] for key in priority))
    rows = []
    for key, stats in result["stats"].items():
        name, unit, reason = REGION_FACTORS[key]
        terms = result["model"]["terms"] if result["model"] else {}
        trend = " · ".join(f"{y} {rho:+.2f}" for y, rho in stats["annual_rho"].items())
        rows.append({"지역 특성": name, "단위": unit, "우리 지역": values.get(key), "비교 지역의 가운데 값": stats.get("median"),
                     "비교 지역 수": stats["n"], "자료 없는 지역 수": stats["eligible"] - stats["n"],
                     "관련성": stats["rho"], "다른 특성도 고려한 차이(%p)": terms.get(key, {}).get("beta"),
                     "연도별 관련성": trend, "지표 설명": reason.replace("표준화율", "나이 구성을 맞춘 비율")})
    with st.expander(f"생활 여건은 {rate_name}과 어떤 관련이 있나요?"):
        st.dataframe(pd.DataFrame(rows).round(2), hide_index=True, column_config={
            "관련성": st.column_config.NumberColumn(
                help=f"Spearman ρ입니다. +1에 가까우면 이 특성과 {rate_name}이 함께 높은 경향, −1에 가까우면 한쪽이 높을 때 다른 쪽이 낮은 경향입니다."
            ),
            "다른 특성도 고려한 차이(%p)": st.column_config.NumberColumn(
                help=f"다른 지역 특성이 같다고 봤을 때, 이 특성이 표준편차만큼 높을 경우의 {rate_name} 차이입니다."
            ),
        })
    if year == 2025 and retail:
        latest = retail.get("latest_row_update") or "미상"
        count = retail.get("district_counts", {}).get(code)
        if count is not None:
            st.caption(f"우리 지역 주소에서 확인된 영업 중 소매점 {count:,}곳.")
        st.caption(f"인허가 자료에서 영업 중인 가게를 세고, 2025년 성인 인구 1만 명당 가게 수를 계산했습니다. "
                   f"전국은 인허가 자료 전체, 시도는 소속 시도를 확인한 주소를 기준으로 계산했습니다. "
                   f"파일 전체의 기준일은 확인되지 않았으며 개별 기록의 가장 최근 갱신일은 {latest}입니다. "
                   "2025년 조사 결과와 참고로 비교했으며, 연도별 회귀 분석에는 포함하지 않았습니다.")
    if result["model"]:
        diagnostics = result["model"]
        spatial = diagnostics["spatial"]
        with st.expander("지역 회귀 진단 · 통계 자세히 보기"):
            st.caption(f"필요한 자료가 모두 있는 {diagnostics['n']}개 지역을 분석했습니다. "
                       f"지역별 차이를 설명하는 정도(R²)는 {diagnostics['r_squared']:.2f}입니다. "
                       f"결과에 영향을 크게 주는 지역은 Cook 거리 기준으로 {diagnostics['influential_n']}곳입니다.")
            if spatial:
                st.caption(f"가까운 4개 지역끼리 분석 후 남은 차이가 비슷한지 살펴봤습니다. "
                           f"Moran’s I {spatial['moran_i']:+.2f} (순열 검정 p={spatial['upper_tail_p']:.3f}). "
                           "이 분석에서는 이웃 지역 간 유사성을 따로 보정하지 않았습니다.")
            st.dataframe(pd.DataFrame.from_dict(diagnostics["terms"], orient="index").rename(
                index=lambda key: REGION_FACTORS[key][0],
                columns={"beta": "다른 특성도 고려한 차이(%p)", "vif": "VIF",
                         "stable_province": "시·도를 하나씩 빼도 방향이 같은가요?",
                         "stable_outliers": "영향이 큰 지역을 빼도 방향이 같은가요?"}).round(2))
    return priority


def render_analysis(code, province, name, requested_year):
    st.title(f"{name} 흡연 관련 요인")
    st.caption(province)
    try:
        data = load_analysis_artifact(ARTIFACT, ARTIFACT.stat().st_mtime_ns)
    except (OSError, ValueError):
        st.warning("전국 분석 결과를 읽을 수 없습니다. `python scripts/build_smoking_analysis.py`로 가공 결과를 생성하세요.")
        return None
    columns = st.columns([2, 1, 2])
    with columns[0]:
        metric = st.selectbox("흡연 지표", list(data["results"]), format_func=METRICS.get, key="analysis_metric")
    rate_name = "담배제품 사용률" if metric == "tobacco" else "흡연율"
    series = data["results"][metric]
    years = sorted(map(int, series))
    initial = requested_year if requested_year in years else years[-1]
    with columns[1]:
        year = st.selectbox("분석 연도", years, index=years.index(initial), key=f"analysis_year_{metric}")
    areas = data.get("areas", {})
    peer = None
    if areas:
        labels = {area_code: f"{area['sido']} {area['sigungu']}" for area_code, area in areas.items() if area_code != code}
        with columns[2]:
            selected_peer = st.selectbox("함께 비교할 시군구", sorted(labels, key=labels.get),
                                         index=None, placeholder="비교할 지역을 골라 주세요",
                                         format_func=labels.get, key=f"analysis_peer_district_{code}")
        if selected_peer is not None:
            peer = (selected_peer, labels[selected_peer])
    year_key = str(year)
    report = series[year_key]
    official = report["official"].get(code, {})
    month = data["metadata"]["population"][year_key]["month"]
    reference, comparison = composition_view(report, code, official, year, month, rate_name)
    official_summary(report, official, province, rate_name)
    with st.expander("해마다 어떻게 달라졌나요?"):
        trend = {y: series[str(y)]["official"].get(code, {}) for y in years}
        rows = []
        for y, row in trend.items():
            comparable = series[str(y)]["comparison"].get(code, {}).get("national_age") or {}
            rows.append({"연도": y, f"실제 조사 {rate_name}(%)": row.get("crude"), f"지역 비교용 {rate_name}(%)": row.get("std"),
                         f"예상 {rate_name}(%)": comparable.get("expected"),
                         "사람들의 구성으로 달라진 만큼(%p)": comparable.get("composition"),
                         "실제와 예상의 차이(%p)": comparable.get("remaining")})
        st.caption("이 표의 예상 수치는 각 해의 전국 나이대별 기준으로 계산했습니다.")
        st.dataframe(pd.DataFrame(rows).round(2), hide_index=True)
    survey = data["metadata"]["survey"].get(year_key, {})
    individual = individual_view(report, code, province, peer, survey, rate_name)
    region = data["regional"].get(metric, {}).get(year_key)
    comparisons = data.get("region_comparisons", {}).get(year_key)
    std = official.get("std")
    gap = std - report["official_national_median"] if std is not None else None
    priority = regional_view(region, comparisons, code, province, peer, gap, data["metadata"].get("retail"), year, rate_name)
    st.header("함께 살펴볼 점")
    if individual:
        factor = SURVEY_FACTORS[individual["factor"]]
        contrast = max(individual["contrasts"], key=lambda row: abs(row["rate_local"] - row["rate_sample"]))
        delta = contrast["rate_local"] - contrast["rate_sample"]
        st.write(f"**{factor} · {contrast['category']}** 집단의 {rate_name}은 우리 지역에서 "
                 f"**{pct(contrast['rate_local'])}**(응답 {contrast['n']}명), 같은 집단의 제공 표본에서 "
                 f"**{pct(contrast['rate_sample'])}**로 **{pp(delta)}** 차이가 납니다.")
    elif report["logistic"]:
        st.write("다변량 로지스틱 회귀는 제공 표본 전체를 바탕으로 계산했습니다. 우리 지역 주민의 특성별 비교는 응답이 충분할 때 표시합니다.")
    if priority:
        names = ", ".join(REGION_FACTORS[key][0] for key in priority)
        st.write(f"지역 자료에서 함께 살펴볼 특성은 **{names}**입니다. 지역별 차이만으로 개인이 왜 흡연하는지는 알 수 없습니다.")
    else:
        st.write(f"우리 지역에서 눈에 띄면서 여러 해 동안 {rate_name}과 꾸준히 관련된 지역 특성은 찾지 못했습니다.")
    payload = {"schema": 1, "region": {"code": code, "province": province, "name": name},
               "year": year, "metric": metric, "official": official, "population_month": month,
               "comparison_district": {"code": peer[0], "name": peer[1]} if peer else None,
               "composition_reference": reference, "composition": comparison,
               "individual": {"scope": "provided_sample", "adjusted": report["logistic"],
                              "district_estimates": [row for row in report["individual"] if row["adm_cd"] == code]},
               "regional": {"factors": region["stats"], "values": region["districts"].get(code, {}),
                            "model": region["model"], "priority": priority,
                            "retail_snapshot": {"date": data["metadata"].get("retail", {}).get("snapshot_date"),
                                                "count": data["metadata"].get("retail", {}).get("district_counts", {}).get(code)}
                            if year == 2025 else None} if region else None}
    st.download_button("선택 지역 분석 JSON", json.dumps(payload, ensure_ascii=False, indent=2),
                       file_name=f"smoking-{code}-{year}-{metric}.json", mime="application/json")
    return year
