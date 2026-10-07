"""Тесты пайплайна на маленьких синтетических NetCDF-файлах (настоящие данные не нужны)."""

import datetime
import json
import shutil
import sys
from pathlib import Path

import netCDF4
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import process_tcr2 as p  # noqa: E402

FILL = -9.99e8
LEVELS = [1000.0, 850.0, 500.0]


def make_nc(path: Path, year: int, base: float = 100.0, mask_surface: bool = True) -> Path:
    """Файл в формате TCR-2: hno3[time, lev, lat, lon] в ppt, время — дни с 2005-01-01."""
    with netCDF4.Dataset(path, "w") as ds:
        ds.ShortName = "TEST3D"
        ds.IdentifierProductDOI = "10.0000/test"
        ds.createDimension("time", 12)
        ds.createDimension("lev", len(LEVELS))
        ds.createDimension("lat", 3)
        ds.createDimension("lon", 4)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "days since 2005-01-01"
        t.calendar = "standard"
        t[:] = netCDF4.date2num([datetime.datetime(year, m, 1) for m in range(1, 13)],
                                t.units, t.calendar)
        ds.createVariable("lev", "f4", ("lev",))[:] = LEVELS
        ds.createVariable("lat", "f4", ("lat",))[:] = [50.0, 55.0, 60.0]
        ds.createVariable("lon", "f4", ("lon",))[:] = [0.0, 60.0, 180.0, 300.0]
        v = ds.createVariable("hno3", "f4", ("time", "lev", "lat", "lon"), fill_value=FILL)
        v.units = "ppt"
        data = np.full((12, len(LEVELS), 3, 4), base, dtype="f4")
        data += np.arange(12, dtype="f4")[:, None, None, None]  # месяц влияет на значение
        if mask_surface:
            data[:, 0, :, :] = FILL  # нижний уровень «под землёй»
        v[:] = data
    return path


@pytest.fixture
def cities(tmp_path):
    path = tmp_path / "cities.json"
    path.write_text(json.dumps({"cities": [
        {"name": "A", "lat": 55.2, "lon": 61.4},   # ближайшая ячейка: 55, 60
        {"name": "B", "lat": 59.0, "lon": -59.0},  # 60, 300 (= -60)
    ]}), encoding="utf-8")
    return path


def run(tmp_path, cities, *extra):
    out = tmp_path / "out.json"
    code = p.main(["--input", str(tmp_path / "raw"), "--cities", str(cities),
                   "--substance", "hno3", "--output", str(out), *extra])
    return code, (json.loads(out.read_text(encoding="utf-8")) if out.exists() else None)


def test_year_comes_from_file_not_from_name(tmp_path, cities):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_nc(raw / "file.nc", 2011)     # имя «file.nc» в ВКР считалось 2010 годом
    make_nc(raw / "file1.nc", 2012)
    code, out = run(tmp_path, cities)
    assert code == 0
    assert out["years"] == [2011, 2012]


def test_masked_values_become_null_and_units_converted(tmp_path, cities):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_nc(raw / "a.nc", 2015)
    code, out = run(tmp_path, cities)
    assert code == 0
    assert out["units"] == "ppb"
    january = out["cities"][0]["values"][0][0]
    assert january[0] is None                 # пропуск → null, а не 0
    assert january[1] == pytest.approx(0.1)   # 100 ppt → 0.1 ppb
    july = out["cities"][0]["values"][0][6]
    assert july[1] == pytest.approx(0.106)    # месяц учитывается


def test_identical_duplicate_is_skipped(tmp_path, cities):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_nc(raw / "file10.nc", 2021)
    shutil.copy(raw / "file10.nc", raw / "file11.nc")
    code, out = run(tmp_path, cities)
    assert code == 0
    assert out["years"] == [2021]


def test_different_files_for_same_year_fail(tmp_path, cities):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_nc(raw / "a.nc", 2021, base=100)
    make_nc(raw / "b.nc", 2021, base=200)
    code, out = run(tmp_path, cities)
    assert code == 1
    assert out is None


def test_levels_and_grid_cells(tmp_path, cities):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_nc(raw / "a.nc", 2015)
    _, out = run(tmp_path, cities)
    assert [lv["pressure_hPa"] for lv in out["levels"]] == LEVELS
    assert out["cities"][0]["grid_cell"] == [55.0, 60.0]
    assert out["cities"][1]["grid_cell"] == [60.0, -60.0]   # долгота 300° → -60°


def test_output_is_deterministic(tmp_path, cities):
    raw = tmp_path / "raw"
    raw.mkdir()
    make_nc(raw / "a.nc", 2015)
    _, first = run(tmp_path, cities)
    _, second = run(tmp_path, cities)
    assert first == second


@pytest.mark.parametrize("src,dst,factor", [("ppt", "ppb", 1e-3), ("ppb", "ppm", 1e-3), ("ppm", "ppb", 1e3)])
def test_unit_factor(src, dst, factor):
    assert p.unit_factor(src, dst) == pytest.approx(factor)


def test_nearest_cell_wraps_longitude():
    lats = np.array([0.0])
    lons = np.array([0.0, 90.0, 180.0, 270.0])
    assert p.nearest_cell(lats, lons, 0.0, -85.0) == (0, 3)   # -85° ближе к 270°
    assert p.nearest_cell(lats, lons, 0.0, 359.0) == (0, 0)
