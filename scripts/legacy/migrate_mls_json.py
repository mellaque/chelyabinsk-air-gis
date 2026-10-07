#!/usr/bin/env python3
"""Одноразовый перевод JSON-файлов CO, H₂O и O₃ из версии ВКР в формат schema_version 2.

Исходные NetCDF для этих веществ (Aura MLS) не сохранились, поэтому данные переносятся
как есть, но:
  * значения переводятся из объёмных долей (mol/mol) в ppb / ppm;
  * в файл добавляется пометка quality = "unverified" и описание проблемы;
  * давления уровней не восстановлены (pressure_hPa = null).

Запуск (повторный запуск на уже переведённых файлах ничего не меняет):
    python scripts/legacy/migrate_mls_json.py data/co_data.json data/h2o_data.json data/o3_data.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SETTINGS = {
    "co": {
        "units": "ppb", "factor": 1e9,
        "note": "Данные версии ВКР. На промежуточном этапе значения для разных регионов "
                "оказались одинаковыми, поэтому принадлежность Челябинской области не гарантируется.",
    },
    "h2o": {
        "units": "ppm", "factor": 1e6,
        "note": "Данные версии ВКР. Строки «Челябинск» совпадают с данными другого региона, "
                "поэтому принадлежность Челябинской области не гарантируется.",
    },
    "o3": {
        "units": "ppm", "factor": 1e6,
        "note": "Данные версии ВКР. Исходные файлы не сохранились, проверить значения нельзя.",
    },
}


def round_sig(value: float, digits: int = 4) -> float:
    return float(f"{value:.{digits}g}")


def migrate(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") == 2:
        print(f"{path}: уже в новом формате, пропускаю")
        return

    substance = path.name.split("_")[0]
    cfg = SETTINGS[substance]
    records = [r for c in data["cities"] for r in c["data"]]
    years = sorted({r["year"] for r in records})
    levels = sorted({r["level"] for r in records})
    months = list(range(1, 13))

    cities = []
    for city in data["cities"]:
        lookup = {(r["year"], r["month"], r["level"]): r["concentration"] for r in city["data"]}
        values = [[[None if (v := lookup.get((y, m, lv))) in (None, 0) else round_sig(v * cfg["factor"])
                    for lv in levels] for m in months] for y in years]
        cities.append({"name": city["name"], "coordinates": city["coordinates"], "values": values})

    result = {
        "schema_version": 2,
        "substance": substance,
        "units": cfg["units"],
        "source": {"product": "Aura MLS (версия ВКР)", "title": None, "version": None,
                   "doi": None, "institution": "NASA JPL", "files": []},
        "quality": "unverified",
        "quality_note": cfg["note"],
        "years": years,
        "months": months,
        "levels": [{"level": lv, "pressure_hPa": None} for lv in levels],
        "index_order": ["year", "month", "level"],
        "cities": cities,
    }
    path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{path}: {len(years)} г., {len(levels)} уровней, единицы {cfg['units']}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        migrate(Path(arg))
