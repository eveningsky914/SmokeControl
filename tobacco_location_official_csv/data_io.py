"""공식 CSV 저장·경로 검색. 가상 데이터를 쓰지 않음."""
from __future__ import annotations
from pathlib import Path
import shutil
from analysis_core import KINDS, read_table_bytes, _column

REQUIRED_COLUMNS = {
    "tobacco": (["사업장명", "업소명", "상호명", "담배소매업소명"],
                ["위도", "좌표정보(X)", "좌표정보x", "x좌표", "경도"]),
    "schools": (["학교명", "시설명"], ["위도", "lat", "좌표정보(X)"]),
    "zones": (["대상시설명", "시설명"], ["위도", "lat", "좌표정보(X)"]),
}


def validate_raw(raw: bytes, kind: str):
    if kind not in KINDS:
        raise ValueError("잘못된 데이터 종류")
    df = read_table_bytes(raw)
    names, coords = REQUIRED_COLUMNS[kind]
    if _column(df, names) is None:
        raise ValueError(f"{kind}: 이름 컬럼을 찾지 못했습니다. 업로드한 파일 종류를 확인하세요.")
    if _column(df, coords) is None:
        raise ValueError(f"{kind}: 위치 좌표 컬럼이 없습니다. 원본 CSV를 확인하세요.")
    return len(df)


def find_source(data_dir: Path, kind: str) -> Path | None:
    for suffix in ("csv", "zip"):
        path = data_dir / f"{kind}.{suffix}"
        if path.is_file():
            return path
    return None


def write_source(data_dir: Path, kind: str, raw: bytes, is_zip=False) -> Path:
    validate_raw(raw, kind)
    data_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".zip" if is_zip else ".csv"
    target = data_dir / f"{kind}{suffix}"
    tmp = data_dir / f".{kind}{suffix}.part"
    tmp.write_bytes(raw)
    tmp.replace(target)
    stale = data_dir / f"{kind}{'.csv' if is_zip else '.zip'}"
    if stale.exists():
        stale.unlink()
    return target
