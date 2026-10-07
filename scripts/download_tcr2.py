#!/usr/bin/env python3
"""Загрузка файлов TROPESS Chemical Reanalysis (TCR-2) с NASA GES DISC.

Файлы ищутся в каталоге NASA CMR (без авторизации), а скачиваются с токеном Earthdata Login:

    export EARTHDATA_TOKEN=...                                  # токен из urs.earthdata.nasa.gov
    python scripts/download_tcr2.py --substance co              # все годы 2005–2021
    python scripts/download_tcr2.py --substance hno3 --years 2005-2010
    python scripts/download_tcr2.py --substance o3 --dry-run    # только список файлов, токен не нужен

Повторный запуск докачивает только недостающее: скачанные файлы пропускаются,
прерванная загрузка продолжается с места остановки (файл .part).
Продукты веществ берутся из config/substances.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger("download_tcr2")

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
TOKEN_ENV = "EARTHDATA_TOKEN"
DEFAULT_YEARS = "2005-2021"                 # период реанализа TCR-2
NETCDF_MAGIC = (b"\x89HDF\r\n\x1a\n", b"CDF\x01", b"CDF\x02", b"CDF\x05")
CHUNK = 1 << 20
SIZE_TOLERANCE = 0.01                      # CMR указывает размер в МБ с округлением

AUTH_HINT = (
    "Проверьте:\n"
    f"  1) переменная {TOKEN_ENV} содержит действующий токен (urs.earthdata.nasa.gov → Generate Token);\n"
    "  2) в профиле Earthdata разрешено приложение «NASA GESDISC DATA ARCHIVE»\n"
    "     (Applications → Authorized Apps → Approve More Applications)."
)


class DownloadError(Exception):
    """Ошибка, после которой продолжать загрузку бессмысленно."""


@dataclass(frozen=True)
class Granule:
    name: str
    url: str
    year: int
    size: int | None        # ожидаемый размер в байтах (приблизительно), если известен


# ---------------------------------------------------------------- параметры

def parse_years(spec: str) -> list[int]:
    """'2005-2021' → [2005..2021], '2011,2015' → [2011, 2015], '2019' → [2019]."""
    years: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            if start > end:
                raise ValueError(f"неверный диапазон лет: {part}")
            years.update(range(start, end + 1))
        else:
            years.add(int(part))
    if not years:
        raise ValueError("не указан ни один год")
    return sorted(years)


def load_product(config_path: Path, substance: str) -> tuple[str, str]:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))["substances"]
    if substance not in cfg:
        raise DownloadError(f"Вещество {substance!r} не найдено в {config_path}. Есть: {sorted(cfg)}")
    return cfg[substance]["product"], str(cfg[substance].get("version", "1"))


# ---------------------------------------------------------------- поиск в CMR

def cmr_get(session: requests.Session, url: str, params: dict, headers: dict,
            retries: int = 4, backoff: float = 5.0) -> requests.Response:
    """Запрос к каталогу CMR с повторами: каталог иногда отвечает медленно или с ошибкой 5xx."""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, params=params, headers=headers, timeout=(15, 90))
        except requests.RequestException as e:
            if attempt == retries:
                raise
            log.warning("Каталог CMR: сетевая ошибка %s, повтор (%d/%d)", e.__class__.__name__, attempt, retries)
        else:
            if r.status_code != 429 and r.status_code < 500:
                return r
            if attempt == retries:
                return r
            log.warning("Каталог CMR: HTTP %d, повтор (%d/%d)", r.status_code, attempt, retries)
        time.sleep(backoff * attempt)
    raise AssertionError("недостижимо")


def find_granules(session: requests.Session, product: str, version: str, years: list[int],
                  cmr_url: str = CMR_GRANULES_URL) -> list[Granule]:
    """Список файлов продукта за нужные годы из каталога NASA CMR."""
    params = {
        "short_name": product,
        "version": version,
        "temporal": f"{years[0]}-01-01T00:00:00Z,{years[-1]}-12-31T23:59:59Z",
        "page_size": 200,
        "sort_key": "start_date",
    }
    wanted = set(years)
    found: list[Granule] = []
    headers: dict[str, str] = {}
    while True:
        r = cmr_get(session, cmr_url, params, headers)
        if r.status_code != 200:
            raise DownloadError(f"Каталог CMR вернул HTTP {r.status_code}: {r.text[:200]}")
        entries = r.json().get("feed", {}).get("entry", [])
        for e in entries:
            url = next((link["href"] for link in e.get("links", [])
                        if link.get("rel", "").endswith("/data#")
                        and link.get("href", "").startswith(("https://", "http://"))
                        and link["href"].endswith(".nc")), None)
            if not url:
                continue
            year = int(e["time_start"][:4])
            size_mb = e.get("granule_size")
            size = int(float(size_mb) * 1024 * 1024) if size_mb else None
            if year in wanted:
                found.append(Granule(name=url.rsplit("/", 1)[-1], url=url, year=year, size=size))
        # постраничная выдача CMR: следующая страница по заголовку CMR-Search-After
        search_after = r.headers.get("CMR-Search-After")
        if not search_after or len(entries) < params["page_size"]:
            break
        headers = {"CMR-Search-After": search_after}
    return sorted(found, key=lambda g: (g.year, g.name))


# ---------------------------------------------------------------- загрузка

def looks_like_netcdf(path: Path) -> bool:
    with path.open("rb") as f:
        head = f.read(8)
    return any(head.startswith(m) for m in NETCDF_MAGIC)


def size_ok(actual: int, expected: int | None) -> bool:
    return expected is None or abs(actual - expected) <= expected * SIZE_TOLERANCE


def total_size_from_headers(r: requests.Response) -> int | None:
    """Точный полный размер файла из ответа сервера, если он его сообщил."""
    if r.status_code == 206:                       # Content-Range: bytes 100-999/1000
        total = r.headers.get("Content-Range", "").rpartition("/")[2]
        return int(total) if total.isdigit() else None
    if r.status_code == 200:
        length = r.headers.get("Content-Length", "")
        return int(length) if length.isdigit() else None
    return None


def already_downloaded(path: Path, granule: Granule) -> bool:
    return path.exists() and size_ok(path.stat().st_size, granule.size) and looks_like_netcdf(path)


def download(session: requests.Session, granule: Granule, dest: Path, token: str,
             retries: int = 4, backoff: float = 2.0) -> bool:
    """Скачивает файл. Возвращает True, если скачан, False — если уже был."""
    target = dest / granule.name
    if already_downloaded(target, granule):
        log.info("%s — уже скачан, пропускаю", granule.name)
        return False

    part = target.with_name(target.name + ".part")
    exact_total: int | None = None                 # точный размер, если сервер его сообщил
    for attempt in range(1, retries + 1):
        offset = part.stat().st_size if part.exists() else 0
        headers = {"Authorization": f"Bearer {token}"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            # requests сам убирает заголовок Authorization при редиректе на другой домен
            # (файлы отдаются из облачного хранилища) — токен не уходит посторонним
            with session.get(granule.url, headers=headers, stream=True, timeout=(15, 120)) as r:
                if r.status_code in (401, 403):
                    raise DownloadError(f"{granule.name}: доступ запрещён (HTTP {r.status_code}).\n{AUTH_HINT}")
                if r.status_code == 416 and part.exists():
                    # «Докачивать нечего» — файл уже полностью в .part, проверим его ниже
                    pass
                elif r.status_code == 429 or r.status_code >= 500:
                    wait = float(r.headers.get("Retry-After", backoff * attempt))
                    log.warning("%s: HTTP %d, повтор через %.0f с (%d/%d)",
                                granule.name, r.status_code, wait, attempt, retries)
                    time.sleep(wait)
                    continue
                elif r.status_code not in (200, 206):
                    raise DownloadError(f"{granule.name}: неожиданный ответ HTTP {r.status_code}")
                elif "text/html" in r.headers.get("Content-Type", ""):
                    # вместо файла пришла страница входа Earthdata
                    raise DownloadError(f"{granule.name}: вместо файла получена HTML-страница входа.\n{AUTH_HINT}")
                else:
                    exact_total = total_size_from_headers(r) or exact_total
                    mode = "ab" if r.status_code == 206 else "wb"   # 200 — докачка не поддержана, пишем заново
                    with part.open(mode) as f:
                        for chunk in r.iter_content(CHUNK):
                            f.write(chunk)
        except requests.RequestException as e:
            log.warning("%s: сетевая ошибка %s, повтор (%d/%d)", granule.name, e.__class__.__name__, attempt, retries)
            time.sleep(backoff * attempt)
            continue

        actual = part.stat().st_size if part.exists() else 0
        expected = exact_total if exact_total is not None else granule.size
        complete = actual == exact_total if exact_total is not None else size_ok(actual, granule.size)
        if not complete:
            if expected is not None and actual > expected:
                log.warning("%s: файл больше ожидаемого (%d > %d байт) — скачиваю заново",
                            granule.name, actual, expected)
                part.unlink()
                exact_total = None
            else:
                log.warning("%s: скачано %d из %s байт — докачиваю", granule.name, actual, expected)
            continue
        if not looks_like_netcdf(part):
            part.unlink()
            raise DownloadError(f"{granule.name}: скачанный файл не является NetCDF")
        part.replace(target)
        log.info("%s — скачан (%.1f МБ)", granule.name, actual / 1024 / 1024)
        return True

    raise DownloadError(f"{granule.name}: не удалось скачать за {retries} попыток")


def warn_about_foreign_files(dest: Path, granules: list[Granule]) -> None:
    """В папке лежат .nc, которых нет в каталоге (например, старые копии под другим именем)."""
    known = {g.name for g in granules}
    foreign = sorted(p.name for p in dest.glob("*.nc") if p.name not in known)
    if foreign:
        log.warning("В %s есть файлы не из каталога NASA: %s. process_tcr2.py обработает и их — "
                    "если это старые копии тех же лет, удалите их.", dest, ", ".join(foreign))


# ---------------------------------------------------------------- CLI

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--substance", required=True, help="ключ вещества из config/substances.json (hno3, co, o3, h2o)")
    p.add_argument("--years", default=DEFAULT_YEARS, help="годы: 2005-2021, 2011,2015 или 2019")
    p.add_argument("--output", type=Path, help="папка для файлов (по умолчанию data/raw/<вещество>)")
    p.add_argument("--config", type=Path, default=Path("config/substances.json"))
    p.add_argument("--dry-run", action="store_true", help="только показать список файлов")
    # адрес каталога можно подменить (тесты, зеркала): --cmr-url или переменная CMR_GRANULES_URL
    p.add_argument("--cmr-url", default=os.environ.get("CMR_GRANULES_URL", CMR_GRANULES_URL), help=argparse.SUPPRESS)
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s: %(message)s")
    dest = args.output or Path("data/raw") / args.substance

    try:
        years = parse_years(args.years)
        product, version = load_product(args.config, args.substance)
        token = os.environ.get(TOKEN_ENV, "").strip()
        if not args.dry_run and not token:
            raise DownloadError(f"Не задан токен: export {TOKEN_ENV}=<токен>.\n{AUTH_HINT}")

        with requests.Session() as session:
            session.headers["User-Agent"] = "chelyabinsk-air-gis/download_tcr2"
            granules = find_granules(session, product, version, years, args.cmr_url)
            if not granules:
                raise DownloadError(f"В каталоге нет файлов {product} за {years[0]}–{years[-1]}")
            missing = sorted(set(years) - {g.year for g in granules})
            if missing:
                log.warning("Нет данных %s за годы: %s", product, missing)

            total_mb = sum(g.size or 0 for g in granules) / 1024 / 1024
            log.info("%s v%s: %d файлов, ~%.0f МБ → %s", product, version, len(granules), total_mb, dest)
            if args.dry_run:
                for g in granules:
                    print(f"{g.year}  {g.name}  {g.url}")
                return 0

            dest.mkdir(parents=True, exist_ok=True)
            warn_about_foreign_files(dest, granules)
            downloaded = sum(download(session, g, dest, token) for g in granules)
    except (DownloadError, ValueError) as e:
        log.error("%s", e)
        return 1
    except requests.RequestException as e:
        log.error("Сетевая ошибка: %s", e)
        return 1

    log.info("Готово: скачано %d, уже было %d", downloaded, len(granules) - downloaded)
    return 0


if __name__ == "__main__":
    sys.exit(main())
