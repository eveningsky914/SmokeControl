from zipfile import ZipFile

from pyproj import CRS
import pytest
import shapefile

from education_zones import ARCHIVE_NAME, EducationZones, find_zone_archive


def test_zones_use_polygon_boundaries_and_absolute_priority(tmp_path):
    layer = tmp_path / 'zones'
    with shapefile.Writer(str(layer), shapeType=shapefile.POLYGON) as writer:
        writer.field('PROS_CD', 'C', size=6)
        writer.poly([[(126.98, 37.56), (126.98, 37.57), (126.99, 37.57),
                      (126.99, 37.56), (126.98, 37.56)]])
        writer.record('UOA110')
        writer.poly([[(126.985, 37.555), (126.985, 37.575), (127.01, 37.575),
                      (127.01, 37.555), (126.985, 37.555)],
                     [(126.995, 37.56), (127.0, 37.56), (127.0, 37.565),
                      (126.995, 37.565), (126.995, 37.56)]])
        writer.record('UOA120')
        writer.poly([[(127.02, 37.56), (127.02, 37.57), (127.03, 37.57),
                      (127.03, 37.56), (127.02, 37.56)]])
        writer.record('UOA100')
    layer.with_suffix('.prj').write_text(CRS.from_epsg(4326).to_wkt(), encoding='utf-8')
    archive = tmp_path / ARCHIVE_NAME
    with ZipFile(archive, 'w') as package:
        for suffix in ('.shp', '.shx', '.dbf', '.prj'):
            member = layer.with_suffix(suffix)
            package.write(member, f'data/{member.name}')

    assert find_zone_archive(tmp_path) == archive
    invalid = tmp_path / 'invalid.zip'
    with ZipFile(invalid, 'w') as package:
        package.writestr('zones.csv', '')
    with pytest.raises(ValueError):
        EducationZones.from_zip(invalid)
    zones = EducationZones.from_zip(archive)
    try:
        assert zones.status_at(37.565, 126.988) == '설치 금지'
        assert zones.status_at(37.565, 126.98) == '설치 금지'
        assert zones.status_at(37.566, 127.005) == '심의 필요'
        assert zones.status_at(37.562, 126.998) == '교육환경 심의 대상 아님'
        assert zones.status_at(37.565, 127.025) == '보호구역 유형 확인 필요'
        assert zones.status_at(37.58, 127.04) == '교육환경 심의 대상 아님'
        overlay = zones.boundaries_near(37.565, 126.988, 1000)
        assert [feature['properties']['code'] for feature in overlay['features']] == ['UOA120', 'UOA110']
        relative = overlay['features'][0]['geometry']
        assert relative['type'] == 'Polygon' and len(relative['coordinates']) == 2
        assert zones.boundaries_near(37.565, 127.025, 300)['features'] == []
    finally:
        zones.close()
