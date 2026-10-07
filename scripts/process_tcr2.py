#!/usr/bin/env python3
"""Извлечение значений из месячных 3D-продуктов TROPESS Chemical Reanalysis (TCR-2)
в точках городов и сохранение в JSON для веб-карты.

Пример:
    python scripts/process_tcr2.py \
        --input data/raw/hno3 \
        --cities config/cities.json \
        --substance hno3 \
        --units ppb \
        --output data/hno3_data.json

Что делает скрипт (и чем отличается от версии ВКР):
  * год и месяц берутся из переменной времени внутри файла, а не из имени/порядка файлов;
  * повторяющийся год (например, один и тот же файл, скачанный дважды) обнаруживается;
  * пропущенные значения (masked) сохраняются как null, а не как 0;
  * единицы измерения берутся из атрибута `units` и явно записываются в результат;
  * координаты городов задаются в конфиге, а не в коде.

Формат результата описан в docs/data-format.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import netCDF4
import numpy as np

log = logging.getLogger("process_tcr2")

DATA_DIMS = ("time", "lev", "lat", "lon")

# Единицы: (род величины, множитель к базовой единице). Переводить можно только внутри одного рода.
UNITS = {
    # объёмная доля (концентрации газов)
    "ppt": ("volume", 1e-12),
    "ppb": ("volume", 1e-9),
    "ppm": ("volume", 1e-6),
    "mol/mol": ("volume", 1.0),
    # массовая доля (например, удельная влажность)
    "kg/kg": ("mass", 1.0),
    "g/kg": ("mass", 1e-3),
}
# Как те же единицы записываются в атрибуте units у разных продуктов
UNIT_ALIASES = {
    "pptv": "ppt", "ppbv": "ppb", "ppmv": "ppm",
    "mol mol-1": "mol/mol", "mol mol**-1": "mol/mol", "mol/mol": "mol/mol", "v/v": "mol/mol",
    "kg kg-1": "kg/kg", "kg kg**-1": "kg/kg", "kg/kg": "kg/kg",
    "g kg-1": "g/kg", "g kg**-1": "g/kg",
}


class ProcessingError(Exception):
    """Ошибка во входных данных, при которой продолжать нельзя."""


def normalize_unit(unit: str) -> str:
    """'PPBV ' -> 'ppb', 'kg kg-1' -> 'kg/kg'. Неизвестные единицы возвращаются как есть."""
    u = " ".join(unit.strip().lower().split())
    return UNIT_ALIASES.get(u, u)


def unit_factor(src: str, dst: str) -> float:
    """Множитель для перевода значения из единиц src в dst."""
    s, d = normalize_unit(src), normalize_unit(dst)
    if s not in UNITS or d not in UNITS:
        raise ProcessingError(f"Неизвестные единицы: {src!r} -> {dst!r}. Известные: {sorted(UNITS)}")
    (s_kind, s_scale), (d_kind, d_scale) = UNITS[s], UNITS[d]
    if s_kind != d_kind:
        raise ProcessingError(f"Нельзя перевести {src!r} ({s_kind}) в {dst!r} ({d_kind})")
    return s_scale / d_scale


def round_sig(value: float, digits: int = 4) -> float:
    """Округление до значащих цифр: сохраняет точность и для 0.0003, и для 12.5."""
    return float(f"{value:.{digits}g}")


def nearest_cell(lats: np.ndarray, lons: np.ndarray, lat: float, lon: float) -> tuple[int, int]:
    """Индексы ближайшей ячейки сетки. Долгота сравнивается по кругу (0..360 и -180..180)."""
    i = int(np.argmin(np.abs(lats - lat)))
    dlon = np.abs((lons - lon + 180.0) % 360.0 - 180.0)
    j = int(np.argmin(dlon))
    return i, j


def to_signed_lon(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class YearData:
    year: int
    path: Path
    checksum: str
    units: str
    levels_hpa: list[float]
    # month -> массив по городам [n_cities, n_levels] (masked)
    months: dict[int, np.ma.MaskedArray] = field(default_factory=dict)
    cells: list[tuple[float, float]] = field(default_factory=list)
    attrs: dict[str, str] = field(default_factory=dict)


def find_data_variable(ds: netCDF4.Dataset, name: str | None) -> netCDF4.Variable:
    if name:
        if name not in ds.variables:
            raise ProcessingError(f"В файле нет переменной {name!r}")
        return ds.variables[name]
    candidates = [v for v in ds.variables.values() if tuple(v.dimensions) == DATA_DIMS]
    if len(candidates) != 1:
        names = [v.name for v in candidates]
        raise ProcessingError(f"Не удалось однозначно найти переменную с данными: {names}. Укажите --variable")
    return candidates[0]


def read_file(path: Path, cities: list[dict], variable: str | None, target_units: str) -> YearData:
    with netCDF4.Dataset(path) as ds:
        var = find_data_variable(ds, variable)
        src_units = getattr(var, "units", None)
        if not src_units:
            raise ProcessingError(f"{path.name}: у переменной {var.name!r} нет атрибута units")
        factor = unit_factor(src_units, target_units)

        time = ds.variables["time"]
        dates = netCDF4.num2date(time[:], time.units, getattr(time, "calendar", "standard"))
        years = sorted({d.year for d in dates})
        if len(years) != 1:
            raise ProcessingError(f"{path.name}: в файле несколько лет {years}, ожидается один")

        lats = np.asarray(ds.variables["lat"][:], dtype=float)
        lons = np.asarray(ds.variables["lon"][:], dtype=float)
        levels = [float(p) for p in np.asarray(ds.variables["lev"][:])]

        idx = [nearest_cell(lats, lons, c["lat"], c["lon"]) for c in cities]
        cells = [(float(lats[i]), to_signed_lon(float(lons[j]))) for i, j in idx]

        result = YearData(
            year=years[0],
            path=path,
            checksum=sha256(path),
            units=target_units,
            levels_hpa=levels,
            cells=cells,
            attrs={k: str(ds.getncattr(k)) for k in
                   ("ShortName", "LongName", "VersionID", "IdentifierProductDOI", "institution")
                   if k in ds.ncattrs()},
        )
        for t, date in enumerate(dates):
            # [n_cities, n_levels]; маска сохраняется при умножении
            rows = [np.ma.masked_invalid(var[t, :, i, j]) * factor for i, j in idx]
            result.months[date.month] = np.ma.stack(rows)
        return result


def collect(files: list[Path], cities: list[dict], variable: str | None, units: str) -> dict[int, YearData]:
    by_year: dict[int, YearData] = {}
    for path in files:
        data = read_file(path, cities, variable, units)
        prev = by_year.get(data.year)
        if prev is not None:
            if prev.checksum == data.checksum:
                log.warning("%s — копия %s (год %d), пропускаю", path.name, prev.path.name, data.year)
                continue
            raise ProcessingError(
                f"Два разных файла за {data.year} год: {prev.path.name} и {path.name}")
        if by_year and data.levels_hpa != next(iter(by_year.values())).levels_hpa:
            raise ProcessingError(f"{path.name}: уровни давления отличаются от остальных файлов")
        log.info("%s → %d год, месяцев: %d", path.name, data.year, len(data.months))
        by_year[data.year] = data
    if not by_year:
        raise ProcessingError("Не найдено ни одного файла с данными")
    return by_year


def build_output(by_year: dict[int, YearData], cities: list[dict], substance: str, units: str) -> dict:
    years = sorted(by_year)
    gaps = sorted(set(range(years[0], years[-1] + 1)) - set(years))
    if gaps:
        log.warning("Нет данных за годы: %s", gaps)

    first = by_year[years[0]]
    n_levels = len(first.levels_hpa)
    months = list(range(1, 13))

    out_cities = []
    for ci, city in enumerate(cities):
        values = []
        for y in years:
            year_rows = []
            for m in months:
                arr = by_year[y].months.get(m)
                if arr is None:
                    year_rows.append([None] * n_levels)
                    continue
                row = arr[ci]
                year_rows.append([None if np.ma.is_masked(v) else round_sig(float(v)) for v in row])
            values.append(year_rows)
        cell_lat, cell_lon = first.cells[ci]
        out_cities.append({
            "name": city["name"],
            "coordinates": [city["lat"], city["lon"]],
            "grid_cell": [round(cell_lat, 3), round(cell_lon, 3)],
            "values": values,
        })

    return {
        "schema_version": 2,
        "substance": substance,
        "units": units,
        "source": {
            "product": first.attrs.get("ShortName"),
            "title": first.attrs.get("LongName"),
            "version": first.attrs.get("VersionID"),
            "doi": first.attrs.get("IdentifierProductDOI"),
            "institution": first.attrs.get("institution"),
            "files": [{"name": by_year[y].path.name, "year": y, "sha256": by_year[y].checksum} for y in years],
        },
        "quality": "verified",
        "years": years,
        "months": months,
        "levels": [{"level": k + 1, "pressure_hPa": p} for k, p in enumerate(first.levels_hpa)],
        "index_order": ["year", "month", "level"],
        "cities": out_cities,
    }


def default_units(config_path: Path, substance: str) -> str:
    """Единицы результата из config/substances.json; если вещества там нет — ppb."""
    if config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8")).get("substances", {})
        if substance in cfg and "units" in cfg[substance]:
            return cfg[substance]["units"]
    return "ppb"


def load_cities(path: Path) -> list[dict]:
    cities = json.loads(path.read_text(encoding="utf-8"))["cities"]
    for c in cities:
        if not {"name", "lat", "lon"} <= c.keys():
            raise ProcessingError(f"В {path} у города нет name/lat/lon: {c}")
    return cities


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--input", type=Path, required=True, help="папка с файлами .nc")
    p.add_argument("--cities", type=Path, default=Path("config/cities.json"))
    p.add_argument("--substance", required=True, help="ключ вещества, например hno3")
    p.add_argument("--variable", help="имя переменной в NetCDF (по умолчанию определяется автоматически)")
    p.add_argument("--units", choices=sorted(UNITS),
                   help="единицы результата (по умолчанию — из config/substances.json, иначе ppb)")
    p.add_argument("--substances-config", type=Path, default=Path("config/substances.json"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s: %(message)s")
    try:
        files = sorted(args.input.glob("*.nc"))
        if not files:
            raise ProcessingError(f"В {args.input} нет файлов .nc")
        cities = load_cities(args.cities)
        if args.units is None:
            args.units = default_units(args.substances_config, args.substance)
        by_year = collect(files, cities, args.variable, args.units)
        result = build_output(by_year, cities, args.substance, args.units)
    except ProcessingError as e:
        log.error("%s", e)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    log.info("Готово: %s (%d лет, %d городов, %d уровней)",
             args.output, len(result["years"]), len(result["cities"]), len(result["levels"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
