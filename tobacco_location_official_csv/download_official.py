"""선택적 전국 공공데이터 다운로드 도우미.

외부 datagokr-mcp 패키지를 사용하므로 실제 성공 여부는 포털 접근성과
서비스 정책에 따라 달라질 수 있습니다. 성공한 자료만 데이터 폴더에 저장합니다.
"""
from __future__ import annotations
from pathlib import Path
import subprocess
import sys
import requests
from data_io import find_source, write_source, validate_raw

ROOT=Path(__file__).resolve().parent
IDS={"tobacco":"15045104","schools":"15021148"}
DESC={"tobacco":"담배소매업 인허가","schools":"전국 학교 위치"}


def find_valid_file(folder:Path,kind:str):
    """다운로드된 CSV/ZIP 각각의 형식·필드 검증 후 가장 큰 후보를 선택."""
    found=[]
    for p in folder.rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.csv','.zip'):
            found.append(p)
    found.sort(key=lambda p:p.stat().st_size,reverse=True)
    from data_io import validate_raw
    for candidate in found:
        try:
            raw=candidate.read_bytes()
            rows=validate_raw(raw,kind)
            if rows > 0:
                return candidate,raw,rows
        except (OSError,ValueError,UnicodeError):
            continue
    return None,None,0


def try_tobacco_direct():
    """전국 인허가 제공처의 파일 다운로드 URL(원본 확인 후 유효할 때만 저장)."""
    endpoint = "https://file.localdata.go.kr/file/download/tobacco_retailers/info"
    try:
        response = requests.get(endpoint, timeout=(8,60), stream=True,
                                headers={"User-Agent":"StudentResearchLocationDashboard/1.0"})
        response.raise_for_status()
        chunks=[]
        size=0
        for chunk in response.iter_content(chunk_size=1024*1024):
            if chunk:
                chunks.append(chunk)
                size+=len(chunk)
                if size>600*1024*1024:
                    raise ValueError("파일이 600MB를 초과하여 자동 내려받기를 중단했습니다")
        raw=b''.join(chunks)
        # 다운로드 링크가 HTML 오류/로그인 페이지를 반환한 경우 거절.
        if raw[:1000].lstrip().lower().startswith((b'<html',b'<!doctype')):
            raise ValueError("CSV 대신 HTML이 반환되었습니다")
        rows=validate_raw(raw,'tobacco')
        if not rows:
            raise ValueError("데이터 행이 없습니다")
        # ZIP 여부는 실제 파일 시그니처로 검사.
        import zipfile,io
        zipped=zipfile.is_zipfile(io.BytesIO(raw))
        dest=write_source(ROOT/'data','tobacco',raw,zipped)
        return dest,rows,None
    except (requests.RequestException,ValueError,OSError) as exc:
        return None,0,f"{type(exc).__name__}: {str(exc)[:120]}"


def main():
    print('전국 공식 CSV 다운로드 시도 (공공데이터포털 기반 오픈소스 CLI 활용)')
    print('실패한 자료는 README의 공식 링크에서 직접 내려받아 앱에 업로드해주세요.')
    summary={}
    for kind,ident in IDS.items():
        stage=ROOT/'downloads'/ident
        stage.mkdir(parents=True,exist_ok=True)
        cmd=[sys.executable,'-m','datagokr','download',ident,'--out',str(stage)]
        print(f'\n[{DESC[kind]}] {ident} 데이터 다운로드 시도 중...',flush=True)
        try:
            done=subprocess.run(cmd,capture_output=True,text=True,timeout=240,check=False)
            if done.returncode:
                err=(done.stderr or done.stdout).strip()[-450:]
                print(f'  다운로드 명령 실패 (exit {done.returncode}): {err}')
                if kind=='tobacco':
                    dest,n,err=try_tobacco_direct()
                    if dest:
                        print(f'  ✅ 제공처 직접 다운로드 성공: {n:,}행 → {dest.name}')
                        summary[kind]='성공'
                        continue
                    print(f'  직접 다운로드도 실패: {err}')
                summary[kind]='다운로드 실패'
                continue
            p,data,n=find_valid_file(stage,kind)
            if p is None:
                print('  명령은 끝났지만 유효한 CSV/ZIP이 없습니다. 원본 제공 방식/데이터 구조를 확인하세요.')
                summary[kind]='유효한 CSV 없음'
                continue
            dest=write_source(ROOT/'data',kind,data,p.suffix.lower()=='.zip')
            print(f'  ✅ {n:,}행 CSV 확인: {p.name} → data/{dest.name}')
            summary[kind]='성공'
        except FileNotFoundError:
            print('  datagokr 패키지가 없습니다. python -m pip install datagokr-mcp 실행 필요.')
            summary[kind]='패키지 미설치'
        except subprocess.TimeoutExpired:
            print('  다운로드 시간 초과. 파일이 매우 크거나 서버가 지연 중일 수 있습니다.')
            summary[kind]='시간 초과'
        except Exception as exc:
            print(f'  다운로드 도중 오류: {type(exc).__name__}: {str(exc)[:300]}')
            summary[kind]='오류'
    print('\n=== 결과 ===')
    for k,s in summary.items():print(f'{DESC[k]}: {s}')
    if any(s!='성공' for s in summary.values()):
        print('모든 자료를 받지 못했습니다. README의 공식 다운로드 페이지를 이용해 누락한 CSV를 앱에 올리세요.')
    else:
        print('담배소매점·학교 CSV 연결 완료. python -m streamlit run app.py 로 분석 앱을 실행하세요.')
    if not find_source(ROOT/'data','kindergartens'):
        print('유치원 자료는 유치원알리미(https://e-childschoolinfo.moe.go.kr/openData.do)에서')
        print('일반현황 CSV를 내려받아 앱에 올리거나 data/kindergartens.csv로 저장하세요.')
    return 0 if all(s=='성공' for s in summary.values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
