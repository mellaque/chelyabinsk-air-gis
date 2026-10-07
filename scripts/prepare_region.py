#!/usr/bin/env python3
"""Подготовка границ для карты из GeoJSON, экспортированного из shape-файлов OSM (ГИС-Лаб).

  * исправляет кодировку названий (UTF-8, прочитанный как Windows-1251 при экспорте);
  * оставляет только нужные уровни (по умолчанию область и муниципальные районы/округа);
  * округляет координаты до 5 знаков (~1 м), чтобы уменьшить размер файла.

Пример:
    python scripts/prepare_region.py region_export.geojson data/region.geojson
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def fix_mojibake(text: str | None) -> str | None:
    """'Р§РµР»СЏР±...' -> 'Челяб...'. Уже правильные строки не меняются."""
    if not text:
        return text
    raw = bytearray()
    for ch in text:
        try:
            raw += ch.encode("cp1251")
        except UnicodeEncodeError:
            # Байт 0x98 в cp1251 не определён и при экспорте превратился в U+0098 —
            # возвращаем его как есть (так восстанавливается, например, буква «И»).
            if 0x80 <= ord(ch) <= 0x9F:
                raw.append(ord(ch))
            else:
                return text
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return text


def round_coords(coords, digits: int):
    if isinstance(coords, (int, float)):
        return round(coords, digits)
    return [round_coords(c, digits) for c in coords]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--levels", default="4,6", help="ADMIN_LVL через запятую (4 — область, 6 — районы)")
    p.add_argument("--digits", type=int, default=5)
    args = p.parse_args()

    keep = set(args.levels.split(","))
    src = json.loads(args.input.read_text(encoding="utf-8"))
    features = []
    for f in src["features"]:
        props = f.get("properties") or {}
        if str(props.get("ADMIN_LVL")) not in keep:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "osm_id": int(props["OSM_ID"]) if props.get("OSM_ID") is not None else None,
                "name": fix_mojibake(props.get("NAME")),
                "admin_level": int(props["ADMIN_LVL"]),
            },
            "geometry": {
                "type": f["geometry"]["type"],
                "coordinates": round_coords(f["geometry"]["coordinates"], args.digits),
            },
        })

    out = {"type": "FeatureCollection", "features": features}
    args.output.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{args.output}: {len(features)} объектов из {len(src['features'])}")


if __name__ == "__main__":
    main()
