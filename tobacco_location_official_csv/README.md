# 전국 담배소매점 입지환경 분석 — 공식 CSV 기반

## 후보지 검토

- 지도에서 클릭하거나 지도 위의 주소 검색을 사용하면 후보지 주변 유치원·초중고·담배소매점을 표시합니다. 지도 오른쪽에서 좌표를 직접 입력하거나 시설 표시 범위(500~3,000m)와 좌표계를 설정할 수 있습니다.
- **무인 담배판매기 설치**는 교육환경보호구역 ZIP의 경계로 자동 검토합니다. 절대보호구역이면 `설치 금지`, 상대보호구역이면 `심의 필요`로 표시합니다. [교육환경보호구역 SHP ZIP](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=MK&dsId=30158)
- **신규 담배소매점 지정**은 가장 가까운 기존 소매점과의 직선거리를 표시하고 지도 오른쪽의 비교값(기본 50m)과 비교합니다. 실제 지정 기준과 거리 측정 방법은 관할 시·군·구 규칙을 확인하세요. [담배사업법 시행규칙 제7조의3](https://law.go.kr/LSW/lumLsLinkPop.do?chrClsCd=010202&lspttninfSeq=57811)

## 실행 방법 (VS Code)

1. 이 폴더를 VS Code에서 엽니다.
2. 터미널에서 `python -m pip install -r requirements.txt` 실행
3. `python -m streamlit run app.py` 실행
4. `http://localhost:8501`에 접속합니다.

`VSCode_실행.bat`을 더블클릭해도 실행할 수 있습니다 (Windows + Python 설치 필요).

## 배포 데이터

앱은 `app.py` 옆의 `data/` 폴더를 자동으로 읽습니다. 원본 데이터는 Git에서 제외되므로 배포 파일에 아래 자료를 함께 넣습니다.

| 파일 | 데이터 출처 |
| --- | --- |
| `data/tobacco.csv` | [행정안전부 담배소매업 인허가](https://www.data.go.kr/data/15045104/fileData.do) |
| `data/schools.csv` | [전국초중등학교위치표준데이터](https://www.data.go.kr/data/15021148/standard.do) |
| `data/kindergartens.csv` | [유치원알리미 일반현황](https://e-childschoolinfo.moe.go.kr/openData.do) |
| `data/education_zones.zip` | [브이월드 교육환경보호구역](https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?svcCde=MK&dsId=30158) |

시설 CSV는 같은 이름의 ZIP으로도 제공할 수 있습니다. 교육환경보호구역은 SHP·SHX·DBF·PRJ가 들어 있는 ZIP을 사용하며 브이월드 원본 이름인 `A2SM_SCHULENVRNSNITATPRFCTNZONE.zip`도 인식합니다.

## 데이터 해석의 주의사항

- 담배소매업 좌표 X/Y는 데이터셋에서 설명한 **EPSG:5174**를 기본값으로 사용하여 WGS84로 변환합니다. 다른 자료는 원본 좌표계를 확인해야 합니다.
- 자료에 영업상태가 있는 경우 정상/영업 시설만 사용하도록 필터합니다. **상태 미확인 시 정확성에 유의**하세요.
- 유치원·학교 좌표는 시설을 찾는 데 쓰며 자동 판정은 연결된 보호구역 자료의 기준 시점과 범위를 따릅니다.
- CSV에 좌표가 누락된 시설은 지도에 나올 수 없습니다. CSV의 지역 커버리지와 갱신일을 확인하세요.
- `secrets.toml`과 카카오 API 키는 필요하지 않습니다.

## 테스트

```powershell
python -m pytest -q
```
