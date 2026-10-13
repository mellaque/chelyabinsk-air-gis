"""Тесты копирования библиотек фронтенда (scripts/vendor_frontend.py) на поддельном node_modules."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import vendor_frontend as vf  # noqa: E402

PACKAGES = ("leaflet", "chart.js", "@fortawesome/fontawesome-free", "@fontsource/open-sans")


def font_face(subset: str, weight: int) -> str:
    name = f"open-sans-{subset}-{weight}-normal"
    return (f"/* {name} */\n@font-face {{\n  font-family: 'Open Sans';\n  font-weight: {weight};\n"
            f"  src: url(./files/{name}.woff2) format('woff2'), url(./files/{name}.woff) format('woff');\n"
            f"  unicode-range: U+0000-00FF;\n}}\n\n")


@pytest.fixture
def node_modules(tmp_path):
    """node_modules со всеми файлами, которые берёт скрипт; в CSS шрифта есть и лишнее подмножество."""
    nm = tmp_path / "node_modules"
    for package in PACKAGES:
        (nm / package).mkdir(parents=True)
        (nm / package / "package.json").write_text(json.dumps({"version": "1.0.0"}), encoding="utf-8")
    for source in vf.FILES.values():
        path = nm / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"содержимое {source}".encode())
    for weight in vf.FONT_WEIGHTS:
        css = "".join(font_face(s, weight) for s in ("greek", *vf.FONT_SUBSETS))
        (nm / vf.FONT_PACKAGE / f"{weight}.css").write_text(css, encoding="utf-8")
    return nm


def run(node_modules, vendor, *args):
    return vf.main(["--node-modules", str(node_modules), "--vendor", str(vendor), *args])


def test_vendor_then_check_passes(node_modules, tmp_path):
    vendor = tmp_path / "vendor"
    assert run(node_modules, vendor) == 0
    assert run(node_modules, vendor, "--check") == 0
    assert (vendor / "leaflet/leaflet.js").read_bytes() == (node_modules / "leaflet/dist/leaflet.js").read_bytes()


def test_font_css_keeps_selected_subsets_and_woff2_only(node_modules):
    css = vf.font_css(node_modules).decode("utf-8")
    for weight in vf.FONT_WEIGHTS:
        for subset in vf.FONT_SUBSETS:
            assert f"open-sans-{subset}-{weight}-normal.woff2" in css
    assert "greek" not in css
    assert ".woff)" not in css


def test_check_reports_changed_missing_and_extra_files(node_modules, tmp_path, capsys):
    vendor = tmp_path / "vendor"
    run(node_modules, vendor)
    (vendor / "chart.js/chart.umd.js").write_text("подменённый файл", encoding="utf-8")
    (vendor / "leaflet/leaflet.css").unlink()
    (vendor / "leaflet/extra.js").write_text("лишний", encoding="utf-8")
    capsys.readouterr()

    assert run(node_modules, vendor, "--check") == 1
    out = capsys.readouterr().out
    assert "отличается от пакета: vendor/chart.js/chart.umd.js" in out
    assert "нет файла: vendor/leaflet/leaflet.css" in out
    assert "лишний файл: vendor/leaflet/extra.js" in out


def test_vendor_removes_stale_files(node_modules, tmp_path):
    vendor = tmp_path / "vendor"
    (vendor / "old-library").mkdir(parents=True)
    (vendor / "old-library/old.js").write_text("старая библиотека", encoding="utf-8")
    assert run(node_modules, vendor) == 0
    assert not (vendor / "old-library").exists()


def test_without_node_modules_explains_what_to_do(tmp_path, capsys):
    assert run(tmp_path / "node_modules", tmp_path / "vendor", "--check") == 2
    assert "npm ci" in capsys.readouterr().err
