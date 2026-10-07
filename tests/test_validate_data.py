"""Тесты проверки формата данных (scripts/validate_data.py)."""

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_data as v  # noqa: E402


def test_repository_data_is_valid():
    """Данные, которые лежат в репозитории, должны проходить проверку."""
    assert v.main([]) == 0


@pytest.fixture
def data_dir(tmp_path):
    """Копия data/ во временной папке, которую тесты могут портить."""
    target = tmp_path / "data"
    target.mkdir()
    for f in (ROOT / "data").glob("*.json"):
        shutil.copy(f, target / f.name)
    shutil.copy(ROOT / "data" / "region.geojson", target / "region.geojson")
    return target


def run(data_dir):
    return v.main(["--data-dir", str(data_dir), "--cities", str(ROOT / "config" / "cities.json")])


def edit(path: Path, change):
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_copy_is_valid(data_dir):
    assert run(data_dir) == 0


def test_old_format_is_rejected(data_dir):
    """Файл в формате версии ВКР (список записей без schema_version) не проходит."""
    old = {"cities": [{"name": "Челябинск", "coordinates": [55.16, 61.4],
                       "data": [{"year": 2010, "month": 1, "level": 1, "concentration": 0.0}]}]}
    (data_dir / "hno3_data.json").write_text(json.dumps(old), encoding="utf-8")
    assert run(data_dir) == 1


def test_wrong_shape_is_rejected(data_dir):
    def drop_level(d):
        d["cities"][0]["values"][0][0].pop()
    edit(data_dir / "hno3_data.json", drop_level)
    assert run(data_dir) == 1


def test_nan_is_rejected(data_dir):
    def put_nan(d):
        d["cities"][0]["values"][0][0][5] = float("nan")
    edit(data_dir / "hno3_data.json", put_nan)
    assert run(data_dir) == 1


def test_unverified_needs_note(data_dir):
    """Тест сам делает файл «непроверенным», а не полагается на текущее содержимое data/."""
    def make_unverified(d):
        d["quality"] = "unverified"
        d.pop("quality_note", None)
    edit(data_dir / "co_data.json", make_unverified)
    assert run(data_dir) == 1


def test_cities_must_match_config(data_dir):
    def rename(d):
        d["cities"][0]["name"] = "Екатеринбург"
    edit(data_dir / "hno3_data.json", rename)
    assert run(data_dir) == 1


def test_mojibake_in_region_is_rejected(data_dir):
    def break_name(g):
        g["features"][0]["properties"]["name"] = "Челябинская область".encode().decode("cp1251")
    edit(data_dir / "region.geojson", break_name)
    assert run(data_dir) == 1


def test_report_collects_all_errors():
    report = v.Report()
    shape = (1, 12, 2)
    values = [[[None, 1.0]] * 11 + [[None, -1.0]]]   # одна отрицательная концентрация
    v.validate_values(copy.deepcopy(values), shape, "x", report)
    assert len(report.errors) == 1
    assert "отрицательная" in report.errors[0]
