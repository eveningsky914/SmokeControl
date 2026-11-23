"""전국 담배소매점 입지 분석: 공공데이터 정규화와 공간 인덱스.

결과는 정책 검토용 보조 지표로 법적 인허가 판정이나 인과효과 추정이 아님.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import math
import re
import zipfile
from typing import Mapping

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

EARTH_RADIUS_M = 6_371_000.0
WEIGHTS = {"학교 거리": 40, "어린이보호구역 기준점 거리": 20,
           "기존 판매점 밀도": 25, "판매점 간 거리": 15}
KINDS = ("tobacco", "schools", "zones")
EMPTY_FRAME = ("lat", "lon", "name", "address")


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9가-힣]", "", str(value).lower())


def _column(frame: pd.DataFrame, names: list[str]) -> str | None:
    lookup = {_key(c): c for c in frame.columns}
    return next((lookup[_key(n)] for n in names if _key(n) in lookup), None)


def _single_csv(data: bytes) -> pd.DataFrame:
    errors = []
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            frame = pd.read_csv(io.BytesIO(data), encoding=encoding,
                                dtype=str, low_memory=False, on_bad_lines="skip")
            if len(frame.columns) < 2:
                frame = pd.read_csv(io.BytesIO(data), encoding=encoding, dtype=str,
                                    sep=None, engine="python", on_bad_lines="skip")
            if len(frame.columns) < 2:
                raise ValueError("컬럼을 구분할 수 없습니다")
            frame.columns = [str(c).replace("\ufeff", "").strip() for c in frame.columns]
            return frame
        except (UnicodeDecodeError, ValueError, pd.errors.ParserError) as exc:
            errors.append(f"{encoding}: {exc}")
    raise ValueError("CSV를 읽을 수 없습니다. UTF-8 또는 CP949 파일인지 확인해 주세요. " + "; ".join(errors[:2]))


def read_table_bytes(data: bytes) -> pd.DataFrame:
    """CSV 또는 CSV가 하나/여러 개 담긴 ZIP 지원; XLSX는 CSV 변환 필요."""
    if not data:
        raise ValueError("파일이 비어 있습니다")
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return _single_csv(data)
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        members = [f for f in package.infolist() if f.filename.lower().endswith('.csv')
                   and not f.filename.startswith('__MACOSX/') and not f.is_dir()]
        if not members:
            raise ValueError("ZIP 안에 CSV 파일이 없습니다")
        if sum(f.file_size for f in members) > 1_500_000_000:
            raise ValueError("압축 해제 후 1.5GB 초과. 파일을 나누거나 원본 CSV를 사용하세요")
        if len(members) > 100:
            raise ValueError("ZIP에 CSV가 100개 이상 있습니다. 주요 데이터만 묶어 주세요")
        frames = [_single_csv(package.read(member)) for member in members]
    return pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]


def _numeric(series: pd.Series) -> np.ndarray:
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce").to_numpy(dtype=float)


def normalize_dataset(raw: bytes, kind: str, xy_crs: str = "EPSG:5174") -> tuple[pd.DataFrame, dict]:
    if kind not in KINDS:
        raise ValueError(f"데이터 유형을 확인하세요: {kind}")
    original = read_table_bytes(raw)
    initial_size = len(original)
    df = original.copy()
    status_note = "상태 컬럼 없음 (모든 행 포함)"
    if kind == "tobacco":
        status_candidates = ["영업상태명", "상세영업상태명", "영업상태", "상태명", "영업여부"]
        for target in status_candidates:
            col = _column(df, [target])
            if not col:
                continue
            values = df[col].fillna("").astype(str).str.strip()
            open_rows = values.str.contains("영업|정상|운영|계속", regex=True)
            closed = values.str.contains("폐업|취소|말소|휴업|정지|종료", regex=True)
            valid = open_rows & ~closed
            if valid.any():
                df = df.loc[valid].copy()
                status_note = f"{col}: 확인된 영업/정상 상태만 반영"
                break
            status_note = f"{col}: 상태 코드 판독 불가 (미확인 행 포함)"
    elif kind == "schools":
        col = _column(df, ["운영상태", "운영여부", "학교상태"])
        if col:
            closed = df[col].fillna("").str.contains("폐교|폐지|폐쇄|휴교|미운영")
            df = df.loc[~closed].copy()
            status_note = f"{col}: 폐교·폐지 등 제외"

    lat_col = _column(df, ["위도", "lat", "latitude", "wgs84위도", "y_wgs84"])
    lon_col = _column(df, ["경도", "lng", "lon", "longitude", "wgs84경도", "x_wgs84"])
    x_col = _column(df, ["좌표정보(X)", "좌표정보x", "x좌표", "좌표x", "x", "xcoord", "xcoordinate"])
    y_col = _column(df, ["좌표정보(Y)", "좌표정보y", "y좌표", "좌표y", "y", "ycoord", "ycoordinate"])

    if lat_col and lon_col:
        lat = _numeric(df[lat_col]); lon = _numeric(df[lon_col])
        coord_note = f"위도/경도: {lat_col} / {lon_col}"
    elif x_col and y_col:
        transform = Transformer.from_crs(xy_crs, "EPSG:4326", always_xy=True)
        lon, lat = transform.transform(_numeric(df[x_col]), _numeric(df[y_col]))
        coord_note = f"투영좌표 X/Y → WGS84 ({xy_crs})"
    else:
        raise ValueError("위도·경도 또는 좌표정보(X)/좌표정보(Y)가 없습니다. 주소만 있다면 위경도 변환 후 업로드하세요")
    good = (np.isfinite(lat) & np.isfinite(lon) & (lat >= 32.0) &
            (lat <= 39.5) & (lon >= 123) & (lon <= 133))
    name_aliases = {
        "tobacco": ["사업장명", "업소명", "상호명", "사업장명칭", "상호", "담배소매업소명", "소매업소명"],
        "schools": ["학교명", "시설명"],
        "zones": ["대상시설명", "시설명", "학교명"],
    }
    name_col = _column(df, name_aliases[kind])
    addr_col = _column(df, ["소재지도로명주소", "도로명전체주소", "도로명주소", "사업장도로명주소",
                            "소재지주소", "소재지지번주소", "지번주소"])
    accepted = df.loc[good]
    names = accepted[name_col].fillna("이름 미제공").to_numpy(dtype=str) if name_col else np.full(good.sum(), kind)
    addresses = accepted[addr_col].fillna("").to_numpy(dtype=str) if addr_col else np.full(good.sum(), "")
    normalized = pd.DataFrame({"lat": np.asarray(lat)[good], "lon": np.asarray(lon)[good],
                               "name": names, "address": addresses})
    normalized = normalized.drop_duplicates(subset=["lat", "lon", "name"]).reset_index(drop=True)
    return normalized, {"전체 행": initial_size, "상태 필터 후": len(df),
                        "좌표 유효": len(normalized), "좌표 방식": coord_note,
                        "상태 처리": status_note, "좌표 누락/제외": len(df) - int(good.sum())}


def haversine_m(lat: float, lon: float, other_lat, other_lon) -> np.ndarray:
    a1, b1 = np.radians(float(lat)), np.radians(float(lon))
    a2 = np.radians(np.asarray(other_lat, dtype=float))
    b2 = np.radians(np.asarray(other_lon, dtype=float))
    h = np.sin((a2-a1)/2)**2 + np.cos(a1)*np.cos(a2)*np.sin((b2-b1)/2)**2
    return EARTH_RADIUS_M * 2 * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def _xyz(lat, lon) -> np.ndarray:
    phi, theta = np.radians(np.asarray(lat, dtype=float)), np.radians(np.asarray(lon, dtype=float))
    return np.column_stack([np.cos(phi)*np.cos(theta), np.cos(phi)*np.sin(theta), np.sin(phi)])


@dataclass
class SpatialDataset:
    frame: pd.DataFrame
    tree: cKDTree | None
    xyz: np.ndarray

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "SpatialDataset":
        coords = frame.loc[:, ["lat", "lon"]]
        if coords.empty:
            return cls(frame, None, np.empty((0,3), dtype=float))
        vectors = _xyz(coords["lat"].to_numpy(), coords["lon"].to_numpy())
        return cls(frame, cKDTree(vectors, leafsize=32), vectors)

    def near(self, lat: float, lon: float, radius_m: float) -> tuple[np.ndarray, np.ndarray]:
        if self.tree is None:
            return np.array([], dtype=int), np.array([], dtype=float)
        center = _xyz([lat], [lon])[0]
        chord = 2.0 * math.sin(radius_m / (2.0 * EARTH_RADIUS_M))
        indices = np.asarray(self.tree.query_ball_point(center, chord + 1e-12), dtype=int)
        if len(indices) == 0:
            return indices, np.array([], dtype=float)
        selected = self.frame.iloc[indices]
        distances = haversine_m(lat, lon, selected["lat"], selected["lon"])
        inside = distances <= radius_m + 0.001
        return indices[inside], distances[inside]

    def closest(self, lat: float, lon: float) -> float | None:
        if self.tree is None:
            return None
        _, idx = self.tree.query(_xyz([lat], [lon])[0])
        item = self.frame.iloc[int(idx)]
        return float(haversine_m(lat, lon, [item["lat"]], [item["lon"]])[0])


def ensure_index(value: SpatialDataset | pd.DataFrame | None) -> SpatialDataset:
    if isinstance(value, SpatialDataset):
        return value
    if value is None:
        value = pd.DataFrame(columns=EMPTY_FRAME)
    return SpatialDataset.from_frame(value)


def score_for_distance(distance: float, limits: list[float], grades: list[int]) -> int:
    for limit, grade in zip(limits, grades):
        if distance < limit:
            return grade
    return grades[-1]


def analyze(lat: float, lon: float, datasets: Mapping[str, SpatialDataset | pd.DataFrame],
            min_gap: int = 50, show_radius_m: int = 1200) -> dict:
    indices = {kind: ensure_index(datasets.get(kind)) for kind in KINDS}
    nearest: dict[str, float | None] = {}
    close: dict[str, pd.DataFrame] = {}
    available: dict[str, bool] = {}
    for kind, obj in indices.items():
        available[kind] = obj.tree is not None
        nearest[kind] = obj.closest(lat, lon)
        near_indices, distances = obj.near(lat, lon, show_radius_m)
        if len(near_indices) > 600:
            keep = np.argsort(distances)[:600]
            near_indices, distances = near_indices[keep], distances[keep]
        frame = obj.frame.iloc[near_indices].copy()
        frame["거리(m)"] = np.rint(distances).astype(int)
        close[kind] = frame.sort_values("거리(m)").reset_index(drop=True)
    tobacco = indices["tobacco"]
    n500 = len(tobacco.near(lat, lon, 500)[0])
    n1000 = len(tobacco.near(lat, lon, 1000)[0])
    density = round(n500 / (math.pi * .5**2), 1) if available["tobacco"] else None
    # 원본 CSV가 일부 지자체만 담고 있을 때 멀리 있는 레코드를
    # 전국의 완전한 데이터처럼 취급해 높은 적합도 점수를 주지 않습니다.
    near_10km = {k: (d is not None and d <= 10_000) for k, d in nearest.items()}
    usable = {k: available[k] and near_10km[k] for k in KINDS}
    comp = {}
    if usable["schools"]:
        comp["학교 거리"] = score_for_distance(nearest["schools"], [100, 200, 350, 500], [0, 20, 55, 80, 100])
    if usable["zones"]:
        comp["어린이보호구역 기준점 거리"] = score_for_distance(nearest["zones"], [100, 200, 350], [0, 25, 60, 100])
    if usable["tobacco"]:
        comp["기존 판매점 밀도"] = 100 if n500 <= 2 else 75 if n500 <= 5 else 45 if n500 <= 10 else 15
        comp["판매점 간 거리"] = score_for_distance(nearest["tobacco"],
                         [min_gap, max(min_gap+50,100), max(min_gap+150,200)], [0,35,70,100])
    weight = sum(WEIGHTS[k] for k in comp)
    score = round(sum(WEIGHTS[k] * comp[k] for k in comp) / weight) if weight else None
    suspect = available["tobacco"] and nearest["tobacco"] < min_gap
    # 업로드한 서울 자료를 부산 후보지 평가에 사용하지 않도록 안전장치.
    coverage_unknown = bool(any(available.values()) and not any(usable.values()))
    if coverage_unknown:
        score = None
        level = "해당 지역 데이터 범위 확인 필요 · 점수 보류"
    elif not comp:
        level = "데이터 없음 · 평가 불가"
    elif suspect:
        level = "소매점 거리기준 미달 의심 · 현장확인 우선"
    elif score >= 80:
        level = "정책 지표상 상대적 위험 낮음 · 법적 가능 여부 미판정"
    elif score >= 60:
        level = "보통 · 청소년 보호 영향 정밀 검토"
    else:
        level = "청소년 보호·기존 점포 밀도 측면 주의"
    notes = []
    if coverage_unknown:
        notes.append("모든 데이터 종류에서 10km 이내 등록 지점이 없어 점수를 보류합니다. 해당 지역 자료가 실제로 포함됐는지 확인하세요. (10km는 데이터 품질 경고용 설정값)")
    if suspect:
        notes.append(f"기존 소매점까지 직선거리 약 {nearest['tobacco']:.0f}m: 설정한 비교기준 {min_gap}m보다 짧음. 관할 지자체 규칙·출입구 간 거리 현장 실측 필요")
    if nearest["schools"] is not None and nearest["schools"] < 200:
        notes.append(f"가장 가까운 학교까지 약 {nearest['schools']:.0f}m: 법적 일률 금지거리 아님, 청소년 보호 영향 검토 지표")
    if nearest["zones"] is not None and nearest["zones"] < 200:
        notes.append(f"보호구역 등록 기준점까지 약 {nearest['zones']:.0f}m: 지정 구역 경계와 다름")
    if available["tobacco"] and n500 > 10:
        notes.append(f"반경 500m 안에 기존 점포 {n500}개: 판매점 밀집")
    for k, usable_in_area in usable.items():
        if available[k] and not usable_in_area:
            labels = {"tobacco":"기존 담배소매점", "schools":"학교", "zones":"어린이보호구역"}
            notes.append(f"{labels[k]} 데이터: 가장 가까운 등록 좌표도 10km 밖에 있습니다. 해당 지역이 실제 수록됐는지 확인하기 전까지 이 지표를 점수에서 제외합니다")
    if weight < 100:
        notes.append(f"전체 지표 중 {weight}% 가중치만 산출 가능: 누락·지역범위 불확실 데이터를 제외하고 비례 재계산함")
    return {"score": score, "level": level, "components": comp, "used_weight": weight,
            "nearest": nearest, "count_500": n500, "count_1000": n1000, "density_500": density,
            "suspect": suspect, "notes": notes, "close": close, "available": available,
            "coverage_unknown": coverage_unknown}


def grid_candidates(lat: float, lon: float, datasets: Mapping[str, SpatialDataset | pd.DataFrame],
                    min_gap: int = 50, radius_m: int = 600, steps: int = 9) -> pd.DataFrame:
    spatial = {k: ensure_index(datasets.get(k)) for k in KINDS}
    if not any(d.tree is not None for d in spatial.values()):
        return pd.DataFrame()
    rows = []
    for dy in np.linspace(-radius_m, radius_m, steps):
        for dx in np.linspace(-radius_m, radius_m, steps):
            la = lat + dy/111_320
            lo = lon + dx/(111_320*max(.01, math.cos(math.radians(lat))))
            item = analyze(la, lo, spatial, min_gap, show_radius_m=1000)
            rows.append({"위도": round(la,6), "경도": round(lo,6),
                         "점수": item["score"], "거리미달의심": bool(item["suspect"]),
                         "학교거리(m)": round(item["nearest"]["schools"]) if item["nearest"]["schools"] is not None else None,
                         "기존점거리(m)": round(item["nearest"]["tobacco"]) if item["nearest"]["tobacco"] is not None else None,
                         "보호구역기준점거리(m)": round(item["nearest"]["zones"]) if item["nearest"]["zones"] is not None else None})
    return pd.DataFrame(rows).sort_values(["거리미달의심","점수"], ascending=[True,False], na_position="last").reset_index(drop=True)
