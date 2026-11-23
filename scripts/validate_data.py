import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from src.data_loader import load_rates,load_boundaries
from src.data_validator import validate_rates,match_diagnostics
rates=load_rates(); geo=load_boundaries()
print("rate rows:",len(rates),"years:",sorted(rates.year.dropna().astype(int).unique().tolist()))
for issue in validate_rates(rates): print("ISSUE:",issue)
print(json.dumps(match_diagnostics(geo,rates),ensure_ascii=False,indent=2))
