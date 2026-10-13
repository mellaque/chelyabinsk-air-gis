#!/usr/bin/env python3
"""Библиотеки фронтенда — из пакетов npm в vendor/.

Сайт подключает Leaflet, Chart.js, Font Awesome и шрифт Open Sans из vendor/, а не с CDN:
страница не зависит от чужих серверов, а Content-Security-Policy разрешает скрипты, стили
и шрифты только со своего адреса. Версии — в package.json, архивы и их хеши — в package-lock.json,
так что файлы в vendor/ побайтно совпадают с опубликованными в npm.

    npm ci --ignore-scripts                     # пакеты точно по package-lock.json
    python scripts/vendor_frontend.py           # обновить vendor/
    python scripts/vendor_frontend.py --check   # vendor/ совпадает с пакетами (так проверяет CI)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Open Sans: начертания и подмножества символов. Странице нужны latin («»°–—), cyrillic и math
# (подстрочные цифры в NO₂, O₃); latin-ext и cyrillic-ext — с запасом на новые названия.
FONT_PACKAGE = "@fontsource/open-sans"
FONT_WEIGHTS = (400, 600)
FONT_SUBSETS = ("cyrillic-ext", "cyrillic", "latin-ext", "latin", "math")
FONT_CSS = "open-sans/open-sans.css"

# Файл в vendor/ → файл в node_modules/ (копируется как есть)
FILES = {
    "leaflet/leaflet.js": "leaflet/dist/leaflet.js",
    "leaflet/leaflet.css": "leaflet/dist/leaflet.css",
    "leaflet/images/layers.png": "leaflet/dist/images/layers.png",
    "leaflet/images/layers-2x.png": "leaflet/dist/images/layers-2x.png",
    "leaflet/images/marker-icon.png": "leaflet/dist/images/marker-icon.png",
    "leaflet/images/marker-icon-2x.png": "leaflet/dist/images/marker-icon-2x.png",
    "leaflet/images/marker-shadow.png": "leaflet/dist/images/marker-shadow.png",
    "leaflet/LICENSE": "leaflet/LICENSE",
    "chart.js/chart.umd.js": "chart.js/dist/chart.umd.js",
    "chart.js/LICENSE.md": "chart.js/LICENSE.md",
    "fontawesome/css/fontawesome.min.css": "@fortawesome/fontawesome-free/css/fontawesome.min.css",
    "fontawesome/css/solid.min.css": "@fortawesome/fontawesome-free/css/solid.min.css",
    "fontawesome/webfonts/fa-solid-900.woff2": "@fortawesome/fontawesome-free/webfonts/fa-solid-900.woff2",
    "fontawesome/LICENSE.txt": "@fortawesome/fontawesome-free/LICENSE.txt",
    "open-sans/LICENSE": f"{FONT_PACKAGE}/LICENSE",
    **{
        f"open-sans/files/open-sans-{subset}-{weight}-normal.woff2":
            f"{FONT_PACKAGE}/files/open-sans-{subset}-{weight}-normal.woff2"
        for weight in FONT_WEIGHTS for subset in FONT_SUBSETS
    },
}

FONT_FACE = re.compile(r"/\* open-sans-(?P<subset>[a-z-]+)-(?P<weight>\d+)-normal \*/\s*(?P<rule>@font-face \{.*?\})",
                       re.S)
WOFF_FALLBACK = re.compile(r",\s*url\([^)]*\.woff\) format\('woff'\)")


class VendorError(Exception):
    """Нет нужного пакета или файла в node_modules."""


def package_version(node_modules: Path, package: str) -> str:
    manifest = node_modules / package / "package.json"
    if not manifest.is_file():
        raise VendorError(f"нет {manifest.relative_to(node_modules.parent)} — сначала: npm ci --ignore-scripts")
    return json.loads(manifest.read_text(encoding="utf-8"))["version"]


def font_css(node_modules: Path) -> bytes:
    """@font-face только для нужных начертаний и подмножеств и только woff2 (его понимают все браузеры)."""
    version = package_version(node_modules, FONT_PACKAGE)
    rules = []
    for weight in FONT_WEIGHTS:
        css = (node_modules / FONT_PACKAGE / f"{weight}.css").read_text(encoding="utf-8")
        found = {m["subset"]: m["rule"] for m in FONT_FACE.finditer(css) if m["weight"] == str(weight)}
        for subset in FONT_SUBSETS:
            if subset not in found:
                raise VendorError(f"в {FONT_PACKAGE}/{weight}.css нет подмножества {subset}")
            rules.append(f"/* open-sans-{subset}-{weight}-normal */\n{WOFF_FALLBACK.sub('', found[subset])}\n")
    header = (f"/* Open Sans из {FONT_PACKAGE} {version} (SIL Open Font License 1.1, см. LICENSE).\n"
              f"   Создан scripts/vendor_frontend.py: начертания {', '.join(map(str, FONT_WEIGHTS))}, "
              f"подмножества {', '.join(FONT_SUBSETS)}, только woff2. */\n\n")
    return (header + "\n".join(rules)).encode("utf-8")


def expected_files(node_modules: Path) -> dict[str, bytes]:
    """Что должно лежать в vendor/: путь → содержимое."""
    for package in ("leaflet", "chart.js", "@fortawesome/fontawesome-free", FONT_PACKAGE):
        package_version(node_modules, package)
    result = {}
    for target, source in FILES.items():
        path = node_modules / source
        if not path.is_file():
            raise VendorError(f"нет файла node_modules/{source}")
        result[target] = path.read_bytes()
    result[FONT_CSS] = font_css(node_modules)
    return result


def differences(vendor: Path, expected: dict[str, bytes]) -> list[str]:
    actual = {p.relative_to(vendor).as_posix() for p in vendor.rglob("*") if p.is_file()} if vendor.is_dir() else set()
    problems = [f"нет файла: vendor/{name}" for name in sorted(expected.keys() - actual)]
    problems += [f"отличается от пакета: vendor/{name}" for name in sorted(expected.keys() & actual)
                 if (vendor / name).read_bytes() != expected[name]]
    problems += [f"лишний файл: vendor/{name}" for name in sorted(actual - expected.keys())]
    return problems


def write(vendor: Path, expected: dict[str, bytes]) -> None:
    if vendor.exists():
        shutil.rmtree(vendor)
    for name, content in sorted(expected.items()):
        target = vendor / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Копирует нужные файлы библиотек фронтенда из node_modules в vendor/.")
    parser.add_argument("--check", action="store_true", help="только проверить, что vendor/ совпадает с пакетами")
    parser.add_argument("--node-modules", type=Path, default=ROOT / "node_modules")
    parser.add_argument("--vendor", type=Path, default=ROOT / "vendor")
    args = parser.parse_args(argv)

    try:
        expected = expected_files(args.node_modules)
    except VendorError as err:
        print(f"Ошибка: {err}", file=sys.stderr)
        return 2

    if args.check:
        problems = differences(args.vendor, expected)
        for problem in problems:
            print(problem)
        if problems:
            print("vendor/ не совпадает с пакетами npm. Обновить: python scripts/vendor_frontend.py", file=sys.stderr)
            return 1
        print(f"vendor/ совпадает с пакетами npm: файлов {len(expected)}")
        return 0

    write(args.vendor, expected)
    print(f"vendor/ обновлён: файлов {len(expected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
