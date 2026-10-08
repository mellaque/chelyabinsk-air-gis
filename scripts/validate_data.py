#!/usr/bin/env python3
"""Проверка файлов в data/ на соответствие формату из docs/data-format.md.

Запускается в CI на каждый push и pull request, чтобы в репозиторий не попали данные,
которые сломают карту (старый формат, неверная размерность, NaN, битая кодировка и т. п.).

    python scripts/validate_data.py            # проверить data/ и config/
    python scripts/validate_data.py --data-dir путь/к/data

Код возврата: 0 — всё в порядке, 1 — найдены ошибки (список выводится).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_region import fix_mojibake  # noqa: E402

ALLOWED_UNITS = {"ppt", "ppb", "ppm", "mol/mol", "kg/kg", "g/kg"}
ALLOWED_QUALITY = {"verified", "unverified"}


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def check(self, condition: bool, where: str, message: str) -> bool:
        if not condition:
            self.error(where, message)
        return condition


def display(path: Path) -> str:
    """Короткий путь для сообщений: data/hno3_data.json вместо полного пути."""
    return f"{path.parent.name}/{path.name}"


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_substance_file(path: Path, report: Report) -> dict | None:
    where = display(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        report.error(where, f"не читается как JSON: {e}")
        return None

    if not report.check(data.get("schema_version") == 2, where,
                        f"schema_version должен быть 2, сейчас {data.get('schema_version')!r}"):
        return None

    expected = path.name.removesuffix("_data.json")
    report.check(data.get("substance") == expected, where,
                 f"substance={data.get('substance')!r}, а по имени файла ожидается {expected!r}")
    report.check(data.get("units") in ALLOWED_UNITS, where, f"неизвестные единицы {data.get('units')!r}")

    quality = data.get("quality")
    report.check(quality in ALLOWED_QUALITY, where, f"quality={quality!r}, допустимо {sorted(ALLOWED_QUALITY)}")
    if quality == "unverified":
        report.check(bool(data.get("quality_note")), where, "для непроверенных данных нужен quality_note")
    if quality == "verified":
        source = data.get("source") or {}
        report.check(bool(source.get("doi")), where, "для проверенных данных нужен source.doi")
        report.check(bool(source.get("files")), where, "для проверенных данных нужен список source.files")

    years = data.get("years")
    months = data.get("months")
    levels = data.get("levels")
    ok = report.check(isinstance(years, list) and years and all(isinstance(y, int) for y in years),
                      where, "years — непустой список целых чисел")
    ok &= report.check(ok and years == sorted(set(years)), where, "years должны идти по возрастанию без повторов")
    ok &= report.check(months == list(range(1, 13)), where, "months должен быть [1..12]")
    ok &= report.check(isinstance(levels, list) and bool(levels), where, "levels — непустой список")
    if not ok:
        return None

    for k, level in enumerate(levels):
        lw = f"{where} levels[{k}]"
        report.check(level.get("level") == k + 1, lw, f"level должен быть {k + 1}, сейчас {level.get('level')!r}")
        p = level.get("pressure_hPa")
        report.check(p is None or (is_number(p) and p > 0), lw, f"pressure_hPa должен быть > 0 или null: {p!r}")

    cities = data.get("cities")
    if not report.check(isinstance(cities, list) and bool(cities), where, "cities — непустой список"):
        return None

    shape = (len(years), len(months), len(levels))
    for city in cities:
        name = city.get("name")
        cw = f"{where} город {name!r}"
        report.check(isinstance(name, str) and bool(name), cw, "нет названия")
        coords = city.get("coordinates")
        if report.check(isinstance(coords, list) and len(coords) == 2 and all(map(is_number, coords)),
                        cw, "coordinates должен быть [широта, долгота]"):
            report.check(-90 <= coords[0] <= 90 and -180 <= coords[1] <= 180, cw,
                         f"координаты вне диапазона: {coords}")
        validate_values(city.get("values"), shape, cw, report)
    return data


def validate_values(values, shape: tuple[int, int, int], where: str, report: Report) -> None:
    n_years, n_months, n_levels = shape
    if not report.check(isinstance(values, list) and len(values) == n_years, where,
                        f"values: ожидается {n_years} лет"):
        return
    present = 0
    for yi, year in enumerate(values):
        if not report.check(isinstance(year, list) and len(year) == n_months, where,
                            f"values[{yi}]: ожидается {n_months} месяцев"):
            continue
        for mi, month in enumerate(year):
            if not report.check(isinstance(month, list) and len(month) == n_levels, where,
                                f"values[{yi}][{mi}]: ожидается {n_levels} уровней"):
                continue
            for li, v in enumerate(month):
                if v is None:
                    continue
                if not report.check(is_number(v), where, f"values[{yi}][{mi}][{li}] = {v!r} — не число"):
                    continue
                report.check(v >= 0, where, f"values[{yi}][{mi}][{li}] = {v} — отрицательная концентрация")
                present += 1
    report.check(present > 0, where, "все значения пустые (null)")


def validate_region(path: Path, report: Report) -> None:
    where = display(path)
    try:
        geo = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        report.error(where, f"не читается как JSON: {e}")
        return
    if not report.check(geo.get("type") == "FeatureCollection", where, "ожидается FeatureCollection"):
        return
    features = geo.get("features") or []
    report.check(bool(features), where, "нет объектов")
    regions = 0
    for i, f in enumerate(features):
        fw = f"{where} features[{i}]"
        props = f.get("properties") or {}
        name = props.get("name")
        if report.check(isinstance(name, str) and bool(name), fw, "нет name"):
            report.check(fix_mojibake(name) == name, fw, f"битая кодировка в названии: {name!r}")
        report.check(props.get("admin_level") in (4, 6), fw, f"admin_level={props.get('admin_level')!r}")
        regions += props.get("admin_level") == 4
        geom = f.get("geometry") or {}
        report.check(geom.get("type") in ("Polygon", "MultiPolygon"), fw, f"геометрия {geom.get('type')!r}")
    report.check(regions == 1, where, f"ожидается ровно одна граница области (admin_level 4), найдено {regions}")


def validate_cities_config(config_path: Path, data: dict | None, report: Report) -> None:
    """Города в конфиге и в проверенных данных должны совпадать — иначе данные устарели."""
    if data is None or not config_path.exists():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    expected = [c["name"] for c in config["cities"]]
    actual = [c["name"] for c in data["cities"]]
    report.check(expected == actual, display(config_path),
                 f"города в конфиге {expected} не совпадают с данными {data['substance']}: {actual}. "
                 "Пересоберите данные scripts/process_tcr2.py")


def validate_substance_list(config_path: Path, files: list[Path], report: Report) -> None:
    """Набор веществ в config/substances.json и набор файлов data/*_data.json должны совпадать."""
    if not config_path.exists():
        return
    expected = set(json.loads(config_path.read_text(encoding="utf-8"))["substances"])
    actual = {p.name.removesuffix("_data.json") for p in files}
    for s in sorted(expected - actual):
        report.error(display(config_path), f"нет файла data/{s}_data.json — скачайте и обработайте: "
                                           f"bash scripts/update_data.sh {s}")
    for s in sorted(actual - expected):
        report.error(f"data/{s}_data.json", "вещества нет в config/substances.json")


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--data-dir", type=Path, default=root / "data")
    p.add_argument("--cities", type=Path, default=root / "config" / "cities.json")
    p.add_argument("--substances", type=Path, default=root / "config" / "substances.json")
    args = p.parse_args(argv)

    report = Report()
    files = sorted(args.data_dir.glob("*_data.json"))
    report.check(bool(files), display(args.data_dir), "не найдено ни одного *_data.json")
    for path in files:
        data = validate_substance_file(path, report)
        if data and data.get("quality") == "verified":
            validate_cities_config(args.cities, data, report)
        status = "ok" if not any(e.startswith(display(path)) for e in report.errors) else "ОШИБКИ"
        print(f"{path.name}: {status}")
    validate_substance_list(args.substances, files, report)

    region = args.data_dir / "region.geojson"
    if report.check(region.exists(), display(region), "файл не найден"):
        validate_region(region, report)
        status = "ok" if not any(e.startswith(display(region)) for e in report.errors) else "ОШИБКИ"
        print(f"{region.name}: {status}")

    if report.errors:
        print(f"\nНайдено ошибок: {len(report.errors)}", file=sys.stderr)
        for e in report.errors[:30]:
            print(f"  - {e}", file=sys.stderr)
        if len(report.errors) > 30:
            print(f"  … и ещё {len(report.errors) - 30}", file=sys.stderr)
        return 1
    print("\nВсе файлы данных корректны.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
