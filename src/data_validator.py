from .region_utils import normalize_code

def validate_rates(df):
    issues = []
    if df.empty: return ["통계 자료가 없습니다."]
    if df["adm_cd"].isna().any() or (df["adm_cd"].astype(str).str.strip() == "").any(): issues.append("행정구역 코드가 비어 있는 행이 있습니다.")
    if df.duplicated(["year", "adm_cd"]).any(): issues.append("연도·행정구역 코드 중복이 있습니다.")
    if ((df["rate"].dropna() < 0) | (df["rate"].dropna() > 100)).any(): issues.append("0~100 범위를 벗어난 통계값이 있습니다.")
    return issues

def match_diagnostics(boundaries, rates):
    codes = []
    for feature in boundaries.get("features", []):
        p = feature.get("properties", {})
        code = p.get("adm_cd") or p.get("SIG_CD") or p.get("sigungu_code")
        if code is not None: codes.append(normalize_code(code))
    map_rates = rates[rates["level"] == "sigungu"] if not rates.empty and "level" in rates else rates
    rc = set(map_rates["adm_cd"].dropna().map(normalize_code)) if not map_rates.empty else set()
    bc = set(codes)
    return {"map_regions":len(bc), "stat_regions":len(rc), "matched":len(bc & rc), "unmatched_map":sorted(bc-rc), "unmatched_stats":sorted(rc-bc), "duplicate_boundary_codes":len(codes)-len(bc), "duplicate_rate_rows":int(map_rates.duplicated(["year", "adm_cd"]).sum()) if not map_rates.empty else 0}
