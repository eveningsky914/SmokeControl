from pathlib import Path
import io
import zipfile
import pandas as pd
import pytest
from analysis_core import normalize_dataset,SpatialDataset,analyze
from data_io import validate_raw, write_source,find_source
from download_official import find_valid_file


def test_check_three_official_column_patterns(tmp_path):
    tests={
        'tobacco': '사업장명,영업상태명,좌표정보(X),좌표정보(Y)\n테스트 매장,영업/정상,198000,453000\n',
        'schools': '학교ID,학교명,운영상태,위도,경도\n01,테스트초등학교,운영,37.5037,126.7659\n',
        'zones': '시설종류,대상시설명,위도,경도\n초등학교,테스트초등학교,37.5039,126.7659\n',
    }
    for kind,txt in tests.items():
        raw=txt.encode('utf-8-sig')
        assert validate_raw(raw,kind)==1
        dest=write_source(tmp_path,kind,raw)
        assert find_source(tmp_path,kind)==dest
        frame,meta=normalize_dataset(dest.read_bytes(),kind)
        assert len(frame)==1
    assert find_source(tmp_path,'other') is None


def test_misclassified_school_as_tobacco_is_rejected():
    bad='학교명,위도,경도\n테스트학교,37.5,127.0\n'.encode('utf-8-sig')
    with pytest.raises(ValueError):
        validate_raw(bad,'tobacco')


def test_zip_upload_and_record(tmp_path):
    package=io.BytesIO()
    with zipfile.ZipFile(package,'w') as z:
        z.writestr('시설.csv','대상시설명,위도,경도\n아동시설,37.5,127.0\n')
    zip_dest=write_source(tmp_path,'zones',package.getvalue(),True)
    assert zip_dest.suffix=='.zip'
    assert find_source(tmp_path,'zones')==zip_dest
    frame,meta=normalize_dataset(zip_dest.read_bytes(),'zones')
    assert len(frame)==1


def test_incomplete_data_not_scored(tmp_path):
    raw='학교명,위도,경도\n학교1,37.5037,126.7659\n'.encode()
    dest=write_source(tmp_path,'schools',raw)
    frame,_=normalize_dataset(dest.read_bytes(),'schools')
    data={'schools':SpatialDataset.from_frame(frame)}
    rpt=analyze(37.5037,126.7659,data)
    assert rpt['used_weight']<100
    assert rpt['nearest']['tobacco'] is None


def test_downloader_only_accepts_valid_csv(tmp_path):
    (tmp_path/'wrong.csv').write_text('junk,other\n1,2\n',encoding='utf-8')
    (tmp_path/'school.csv').write_text('학교명,위도,경도\nA,37.5,127\n',encoding='utf-8')
    src,raw,n=find_valid_file(tmp_path,'schools')
    assert src.name=='school.csv' and n==1
    assert find_valid_file(tmp_path,'zones')[0] is None
