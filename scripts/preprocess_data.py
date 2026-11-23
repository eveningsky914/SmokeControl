"""Convert a verified official spreadsheet/CSV; never infer rates or codes."""
from pathlib import Path
import argparse
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("input",type=Path); p.add_argument("--sheet",default=0); args=p.parse_args()
    df=pd.read_excel(args.input,sheet_name=args.sheet) if args.input.suffix.lower() in {".xlsx",".xls"} else pd.read_csv(args.input)
    df=df.rename(columns={"연도":"year","시도":"sido","시군구":"sigungu","행정구역코드":"adm_cd","담배제품 현재사용률":"rate"})
    required=["year","sido","sigungu","adm_cd","rate"]
    if set(required)-set(df.columns): raise SystemExit(f"필수 컬럼 확인 실패: {sorted(set(required)-set(df.columns))}")
    df=df[required].copy(); df["adm_cd"]=df.adm_cd.astype(str).str.replace(r"\.0$","",regex=True)
    df["rate_type"]="표준화율"; df["source"]="질병관리청 지역사회건강조사"
    out=ROOT/"data"/"processed"/"tobacco_rates.csv"; out.parent.mkdir(parents=True,exist_ok=True); df.to_csv(out,index=False,encoding="utf-8-sig")
    print(f"{len(df)} rows -> {out}")
