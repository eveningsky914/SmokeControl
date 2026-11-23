import io
import math
import zipfile
from pathlib import Path
import numpy as np
from pyproj import Transformer
from analysis_core import SpatialDataset, normalize_dataset, analyze, grid_candidates, haversine_m, read_table_bytes


def test_live_status_and_invalid_coordinates():
    csv = ('사업장명,영업상태명,위도,경도,소재지도로명주소\n'
           'A,영업/정상,37.5665,126.978,서울시\n'
           'B,폐업,37.56,126.97,서울시\n'
           'C,영업,999,999,오류\n').encode('utf-8-sig')
    frame,meta=normalize_dataset(csv,'tobacco')
    assert len(frame)==1 and frame['name'].iloc[0]=='A'
    assert meta['전체 행']==3


def test_projected_coordinates():
    x,y=Transformer.from_crs('EPSG:4326','EPSG:5174',always_xy=True).transform(126.978,37.5665)
    frame,meta=normalize_dataset(('사업장명,좌표정보(X),좌표정보(Y)\n'+f'A,{x},{y}\n').encode('cp949'),'tobacco')
    assert abs(frame.iloc[0].lat-37.5665)<1e-5
    assert abs(frame.iloc[0].lon-126.978)<1e-5
    assert '5174' in meta['좌표 방식']


def test_zip_many_csv():
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w') as z:
        z.writestr('a.csv','학교명,위도,경도\n학교A,37.5,127\n')
        z.writestr('b.csv','학교명,위도,경도\n학교B,35.2,129.1\n')
    frame,meta=normalize_dataset(mem.getvalue(),'schools')
    assert len(frame)==2
    assert set(frame['name'])=={'학교A','학교B'}


def test_spatial_index_nearest_counts_and_grid():
    csv=('사업장명,위도,경도\n'
         '첫째,37.5665,126.978\n'
         '둘째,37.5666,126.978\n'
         '셋째,37.5800,126.99\n').encode('utf-8-sig')
    frame,_=normalize_dataset(csv,'tobacco')
    idx=SpatialDataset.from_frame(frame)
    near,dist=idx.near(37.5665,126.978,500)
    assert len(near)==2
    assert min(dist)==0
    report=analyze(37.5665,126.978,{'tobacco':idx})
    assert report['count_500']==2
    assert report['suspect']
    assert report['used_weight']==40
    assert report['components']['판매점 간 거리']==0
    grid=grid_candidates(37.5665,126.978,{'tobacco':idx},steps=3)
    assert len(grid)==9
    assert bool(grid['거리미달의심'].iloc[-1])


def test_uncovered_region_never_gets_high_score():
    frame,_=normalize_dataset('사업장명,위도,경도\nA,37.5665,126.978\n'.encode(),'tobacco')
    s=analyze(35.1796,129.0756,{'tobacco':SpatialDataset.from_frame(frame)})
    assert s['score'] is None and s['coverage_unknown']
    assert '점수 보류' in s['level']


def test_interior_nearest_not_only_radius():
    frame,_=normalize_dataset('학교명,위도,경도\nA,37.6,127.1\n'.encode(),'schools')
    x=SpatialDataset.from_frame(frame)
    assert x.closest(37.5665,126.978)>1000
    assert len(x.near(37.5665,126.978,1200)[0])==0


def test_wgs84_distance():
    out=haversine_m(37.5665,126.978,[37.5665,37.5765],[126.978,126.978])
    assert np.isclose(out[0],0)
    assert 1100<out[1]<1120


def test_status_unknown_not_auto_closed():
    frame,meta=normalize_dataset('사업장명,영업상태명,위도,경도\nA,01,37.5,127\n'.encode(),'tobacco')
    assert len(frame)==1
    assert '판독 불가' in meta['상태 처리']
