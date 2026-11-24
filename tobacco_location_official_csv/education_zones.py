"""Classify candidate points using the bundled education-zone shapefile."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path, PurePosixPath
import shutil
import struct
from tempfile import TemporaryFile
from threading import Lock
from typing import BinaryIO
from zipfile import ZipFile

import numpy as np
from pyproj import CRS, Geod, Transformer
from pyproj.enums import TransformDirection
import shapefile
from shapely import Point, STRtree, box, make_valid, transform
from shapely.geometry import mapping, shape


ARCHIVE_NAME = "education_zones.zip"
OFFICIAL_ARCHIVE_NAME = "A2SM_SCHULENVRNSNITATPRFCTNZONE.zip"
ABSOLUTE = "UOA110"
RELATIVE = "UOA120"
POLYGON_TYPES = (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM)
WGS84 = Geod(ellps='WGS84')


def find_zone_archive(data_dir: Path) -> Path | None:
    for name in (ARCHIVE_NAME, OFFICIAL_ARCHIVE_NAME):
        candidate = data_dir / name
        if candidate.is_file():
            return candidate
    return None


def archive_members(archive: ZipFile) -> dict:
    members = {item.filename.lower(): item for item in archive.infolist() if not item.is_dir()}
    layers = [name for name in members if name.endswith('.shp') and '__macosx/' not in name]
    if len(layers) != 1:
        raise ValueError("ZIP에 교육환경보호구역 SHP 파일 한 개가 필요합니다.")
    stem = str(PurePosixPath(layers[0]).with_suffix(''))
    suffixes = ('.shp', '.shx', '.dbf', '.prj')
    if any(stem + suffix not in members for suffix in suffixes):
        raise ValueError("같은 이름의 SHP·SHX·DBF·PRJ 파일을 ZIP에 함께 넣어 주세요.")
    selected = {suffix: members[stem + suffix] for suffix in suffixes}
    limits = {'.shp': 1_000_000_000, '.shx': 10_000_000, '.dbf': 50_000_000, '.prj': 65_536}
    if any(selected[suffix].file_size > limits[suffix] for suffix in suffixes):
        raise ValueError("압축 해제 후 교육환경보호구역 파일이 너무 큽니다.")
    return selected


class EducationZones:
    def __init__(self, reader: shapefile.Reader, transform: Transformer,
                 bounds: list, records: list[tuple[int, str]], shape_file: BinaryIO):
        self.reader = reader
        self.transform = transform
        self.tree = STRtree(bounds)
        self.records = records
        self.shape_file = shape_file
        self.lock = Lock()

    @classmethod
    def from_zip(cls, path: Path) -> EducationZones:
        shape_file = TemporaryFile()
        try:
            with ZipFile(path) as archive:
                members = archive_members(archive)
                crs = CRS.from_wkt(archive.read(members['.prj']).decode('utf-8-sig'))
                index = archive.read(members['.shx'])
                attributes = archive.read(members['.dbf'])
                with archive.open(members['.shp']) as source:
                    shutil.copyfileobj(source, shape_file, length=1024 * 1024)
                shape_size = shape_file.tell()
            shape_file.seek(0)
            reader = shapefile.Reader(shp=shape_file, shx=BytesIO(index), dbf=BytesIO(attributes),
                                      encoding='cp949', encodingErrors='replace')
            if reader.shapeType not in POLYGON_TYPES:
                raise ValueError("교육환경보호구역은 면 도형(Polygon) 파일이어야 합니다.")
            fields = {field[0].upper(): field[0] for field in reader.fields[1:]}
            code_field = fields.get('PROS_CD') or fields.get('PRPOS_CD')
            if code_field is None:
                raise ValueError("DBF에서 보호구역 용도코드(PROS_CD)를 찾지 못했습니다.")
            if len(index) != 100 + 8 * reader.numRecords:
                raise ValueError("보호구역 도형 인덱스와 DBF 항목 수가 다릅니다.")

            # Read only the bounds first. The official ZIP expands to more than 300 MB.
            bounds = []
            records = []
            for record in reader.iterRecords(fields=[code_field]):
                offset, length = struct.unpack_from('>2i', index, 100 + 8 * record.oid)
                start = offset * 2 + 8
                if offset < 50 or length < 2 or start + length * 2 > shape_size:
                    raise ValueError("보호구역 도형 인덱스가 손상되었습니다.")
                shape_file.seek(start)
                if struct.unpack('<i', shape_file.read(4))[0] == shapefile.NULL:
                    continue
                if length < 18:
                    raise ValueError("보호구역 도형 경계가 손상되었습니다.")
                bounds.append(box(*struct.unpack('<4d', shape_file.read(32))))
                records.append((record.oid, str(record[0]).strip().upper()))
            if not any(code in (ABSOLUTE, RELATIVE) for _, code in records):
                raise ValueError("ZIP에 절대·상대보호구역 코드가 없습니다.")
            return cls(reader, Transformer.from_crs('EPSG:4326', crs, always_xy=True),
                       bounds, records, shape_file)
        except Exception:
            shape_file.close()
            raise

    def close(self) -> None:
        self.shape_file.close()

    def _polygon(self, record_number: int):
        # The reader seeks in a file shared by Streamlit sessions.
        with self.lock:
            record_shape = self.reader.shape(record_number)
        polygon = shape(record_shape.__geo_interface__)
        return polygon if polygon.is_valid else make_valid(polygon)

    def status_at(self, lat: float, lon: float) -> str:
        point = Point(*self.transform.transform(lon, lat))
        codes = set()
        for match in self.tree.query(point):
            record_number, code = self.records[int(match)]
            if self._polygon(record_number).covers(point):
                if code == ABSOLUTE:
                    return "설치 금지"
                codes.add(code)
        if RELATIVE in codes:
            return "심의 필요"
        if codes:
            return "보호구역 유형 확인 필요"
        return "교육환경 심의 대상 아님"

    def boundaries_near(self, lat: float, lon: float, radius_m: int) -> dict:
        west, _, _ = WGS84.fwd(lon, lat, 270, radius_m)
        east, _, _ = WGS84.fwd(lon, lat, 90, radius_m)
        _, south, _ = WGS84.fwd(lon, lat, 180, radius_m)
        _, north, _ = WGS84.fwd(lon, lat, 0, radius_m)
        area = box(*self.transform.transform_bounds(west, south, east, north))

        def to_wgs84(coordinates):
            x, y = self.transform.transform(coordinates[:, 0], coordinates[:, 1],
                                            direction=TransformDirection.INVERSE)
            return np.column_stack((x, y))

        features = []
        for match in self.tree.query(area):
            record_number, code = self.records[int(match)]
            if code not in (ABSOLUTE, RELATIVE):
                continue
            polygon = self._polygon(record_number)
            if polygon.intersects(area):
                outline = transform(polygon, to_wgs84).simplify(0.00002, preserve_topology=True)
                features.append({"type": "Feature", "geometry": mapping(outline), "properties": {"code": code}})
        features.sort(key=lambda feature: feature["properties"]["code"] == ABSOLUTE)
        return {"type": "FeatureCollection", "features": features}
