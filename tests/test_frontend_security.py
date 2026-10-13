"""Страница не загружает чужой код и не содержит встроенных скриптов и стилей — иначе
Content-Security-Policy из index.html заблокировала бы их в браузере (или пришлось бы её ослабить)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
SCRIPTS = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "js").glob("*.js")}


def csp() -> dict[str, list[str]]:
    content = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', HTML).group(1)
    return {d.split()[0]: d.split()[1:] for d in (part.strip() for part in content.split(";")) if d}


def local_resources() -> list[str]:
    return re.findall(r'<(?:script|link)[^>]*\s(?:src|href)="([^"]+)"', HTML)


def test_csp_allows_only_own_code():
    policy = csp()
    assert policy["default-src"] == ["'none'"]
    for directive in ("script-src", "style-src", "font-src", "connect-src"):
        assert policy[directive] == ["'self'"], directive
    assert not [v for values in policy.values() for v in values if v.startswith("'unsafe")]


def test_page_loads_scripts_and_styles_only_from_itself():
    resources = local_resources()
    assert resources, "в index.html не найдено ни одного скрипта или стиля"
    for url in resources:
        assert not re.match(r"(https?:)?//", url), f"внешний ресурс: {url}"
        assert (ROOT / url).is_file(), f"нет файла {url}"


def test_page_has_no_inline_scripts_styles_or_handlers():
    assert "<style" not in HTML
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", HTML), "встроенный <script> без src"
    assert not re.search(r"\sstyle=", HTML), "атрибут style"
    assert not re.search(r"\son[a-z]+=", HTML), "обработчик события в атрибуте"


def test_scripts_do_not_insert_inline_styles_or_handlers():
    for name, js in SCRIPTS.items():
        assert not re.search(r"""style\s*=\s*["']""", js), f"{name}: style=\"…\" в разметке"
        assert not re.search(r"""\son[a-z]+\s*=\s*["']""", js), f"{name}: обработчик события в разметке"
        assert "eval(" not in js and "new Function" not in js, name


def allowed_by(sources: list[str], host: str) -> bool:
    """Разрешает ли список источников CSP загрузку с https://host."""
    for source in sources:
        if source == f"https://{host}":
            return True
        if source.startswith("https://*.") and host.endswith(source[len("https://*"):]):
            return True
    return False


def test_map_tiles_are_allowed_by_csp():
    """Каждый адрес тайлов из app.js (с поддоменом {s} или без) разрешён в img-src."""
    templates = re.findall(r"'(https://[^']*\{z\}[^']*)'", SCRIPTS["app.js"])
    assert templates
    for template in templates:
        host = template.removeprefix("https://").split("/", 1)[0].replace("{s}", "a")
        assert allowed_by(csp()["img-src"], host), host


def test_tile_host_check_understands_csp_wildcards():
    assert allowed_by(["https://*.tile.openstreetmap.org"], "a.tile.openstreetmap.org")
    assert not allowed_by(["https://*.tile.openstreetmap.org"], "tile.openstreetmap.org")
    assert allowed_by(["https://tile.openstreetmap.org"], "tile.openstreetmap.org")


def test_vendored_files_match_package_versions():
    """Версии в шапках файлов vendor/ совпадают с package.json и package-lock.json."""
    wanted = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["dependencies"]
    locked = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    for package, version in wanted.items():
        assert locked[f"node_modules/{package}"]["version"] == version, package
    headers = {
        "leaflet": ("vendor/leaflet/leaflet.js", "Leaflet {}"),
        "chart.js": ("vendor/chart.js/chart.umd.js", "Chart.js v{}"),
        "@fortawesome/fontawesome-free": ("vendor/fontawesome/css/fontawesome.min.css", "Font Awesome Free {}"),
        "@fontsource/open-sans": ("vendor/open-sans/open-sans.css", "@fontsource/open-sans {}"),
    }
    assert set(headers) == set(wanted)
    for package, (path, template) in headers.items():
        head = (ROOT / path).read_text(encoding="utf-8")[:400]
        assert template.format(wanted[package]) in head, path
