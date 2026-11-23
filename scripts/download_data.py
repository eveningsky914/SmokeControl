"""Retry public KDCA attachment downloads; failure never becomes data."""
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
SOURCES={"kdca_2025_summary.zip":"https://www.kdca.go.kr/bbs/kdca/42/305549/download.do"}

def download(url,path):
    try:
        response=requests.get(url,timeout=45); response.raise_for_status()
        if len(response.content)<1024: raise ValueError("응답 파일이 너무 작습니다")
        path.write_bytes(response.content); return True
    except Exception as exc:
        print(f"다운로드 실패: {url} ({exc})"); return False

if __name__=="__main__":
    out=ROOT/"data"/"raw"; out.mkdir(parents=True,exist_ok=True)
    for name,url in SOURCES.items(): print(f"{name}: {'완료' if download(url,out/name) else '실패'}")
