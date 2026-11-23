"""담배소매점·담배자동판매기 입지 검토용 공공데이터 정규화와 공간 검색."""
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
KINDS = ("tobacco", "schools", "kindergartens")
EMPTY_FRAME = ("lat", "lon", "name", "address")
KINDERGARTEN_NAME_COLUMNS = ["유치원명", "유치원 명칭", "kindername"]
LAT_COLUMNS = ["위도", "lat", "latitude", "wgs84위도", "y_wgs84", "lttdcdnt"]
LON_COLUMNS = ["경도", "lng", "lon", "longitude", "wgs84경도", "x_wgs84", "lngtcdnt"]


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
            if (open_rows | closed).any():
                df = df.loc[valid].copy()
                status_note = f"{col}: 확인된 영업/정상 상태만 반영"
                break
            status_note = f"{col}: 상태 코드 판독 불가 (미확인 행 포함)"
    elif kind in ("schools", "kindergartens"):
        col = _column(df, ["운영상태", "운영여부", "학교상태", "유치원상태"])
        if col:
            closed = df[col].fillna("").str.contains("폐교|폐원|폐지|폐쇄|휴교|휴원|미운영")
            df = df.loc[~closed].copy()
            status_note = f"{col}: 폐교·폐원 등 제외"

    lat_col = _column(df, LAT_COLUMNS)
    lon_col = _column(df, LON_COLUMNS)
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
        "kindergartens": KINDERGARTEN_NAME_COLUMNS,
    }
    name_col = _column(df, name_aliases[kind])
    if kind == "kindergartens" and not (name_col and lat_col and lon_col):
        raise ValueError("유치원명·위도·경도가 포함된 유치원 일반현황 CSV를 연결하세요.")
    addr_col = _column(df, ["소재지도로명주소", "도로명전체주소", "도로명주소", "사업장도로명주소",
                            "소재지주소", "소재지지번주소", "지번주소", "주소", "addr"])
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
        site = self.nearest_site(lat, lon)
        return site[1] if site is not None else None

    def nearest_site(self, lat: float, lon: float) -> tuple[pd.Series, float] | None:
        if self.tree is None:
            return None
        _, idx = self.tree.query(_xyz([lat], [lon])[0])
        item = self.frame.iloc[int(idx)]
        distance = float(haversine_m(lat, lon, [item["lat"]], [item["lon"]])[0])
        return item, distance


def ensure_index(value: SpatialDataset | pd.DataFrame | None) -> SpatialDataset:
    if value is None:
        value = pd.DataFrame(columns=EMPTY_FRAME)
    if isinstance(value, pd.DataFrame):
        return SpatialDataset.from_frame(value)
    # Streamlit may cache an index from before the module was reloaded.
    return value


def analyze(lat: float, lon: float, datasets: Mapping[str, SpatialDataset | pd.DataFrame],
            min_gap: int = 50) -> dict:
    nearest = {
        kind: ensure_index(datasets.get(kind)).nearest_site(lat, lon)
        for kind in KINDS
    }
    retailer = nearest["tobacco"]
    if retailer is None:
        retail_check = "자료 확인 필요"
    elif retailer[1] > 10_000:
        retail_check = "지역 데이터 범위 확인 필요"
    elif retailer[1] < min_gap:
        retail_check = "허가 불가"
    else:
        retail_check = "허가 가능"
    return {"nearest": nearest, "retail_check": retail_check}
