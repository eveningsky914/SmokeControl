from pathlib import Path
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RATE_FILE = ROOT / "data" / "processed" / "tobacco_rates.csv"
BOUNDARY_FILE = ROOT / "data" / "processed" / "sigungu.geojson"
SIDO_BOUNDARY_FILE = ROOT / "data" / "processed" / "sido.geojson"

def load_rates(path=RATE_FILE):
    if not Path(path).exists():
        return pd.DataFrame(columns=["year", "sido", "sigungu", "adm_cd", "rate", "rate_type", "source"])
    df = pd.read_csv(path, dtype={"adm_cd":"string"})
    required = {"year", "sido", "sigungu", "adm_cd", "rate"}
    missing = required - set(df.columns)
    if missing: raise ValueError(f"통계 파일 필수 컬럼 누락: {', '.join(sorted(missing))}")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    return df

def load_boundaries(path=BOUNDARY_FILE):
    if not Path(path).exists(): return {"type":"FeatureCollection", "features":[]}
    with Path(path).open(encoding="utf-8") as f: geo = json.load(f)
    if geo.get("type") != "FeatureCollection": raise ValueError("GeoJSON FeatureCollection이 아닙니다.")
    return geo

def load_sido_boundaries(path=SIDO_BOUNDARY_FILE):
    return load_boundaries(path)

def available_years(rates):
    return sorted(int(y) for y in rates["year"].dropna().unique())
