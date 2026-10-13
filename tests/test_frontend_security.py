"""Страница не загружает чужой код и не содержит встроенных скриптов и стилей — иначе
Content-Security-Policy из index.html заблокировала бы их в браузере (или пришлось бы её ослабить).

Имена тегов и атрибутов в HTML не зависят от регистра — браузер выполнит и <SCRIPT>, и ONCLICK=,
поэтому все проверки разметки регистронезависимы (?i)."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
SCRIPTS = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "js").glob("*.js")}


def csp() -> dict[str, list[str]]:
    content = re.search(r'(?i)<meta http-equiv="Content-Security-Policy" content="([^"]+)"', HTML).group(1)
    return {d.split()[0]: d.split()[1:] for d in (part.strip() for part in content.split(";")) if d}


def resources(html: str) -> list[str]:
    """Адреса подключённых скриптов и стилей."""
    return re.findall(r'(?i)<(?:script|link)[^>]*\s(?:src|href)="([^"]+)"', html)


def inline_code(html: str) -> list[str]:
    """Встроенный код в разметке: <style>, <script> без src, атрибуты style= и on…=."""
    found = []
    if "<style" in html.lower():
        found.append("<style>")
    if re.search(r"(?i)<script(?![^>]*\ssrc=)[^>]*>", html):
        found.append("<script> без src")
    if re.search(r"(?i)\sstyle=", html):
        found.append("атрибут style")
    if re.search(r"(?i)\son[a-z]+=", html):
        found.append("обработчик события в атрибуте")
    return found


def test_csp_allows_only_own_code():
    policy = csp()
    assert policy["default-src"] == ["'none'"]
    for directive in ("script-src", "style-src", "font-src", "connect-src"):
        assert policy[directive] == ["'self'"], directive
    assert not [v for values in policy.values() for v in values if v.startswith("'unsafe")]


def test_page_loads_scripts_and_styles_only_from_itself():
    urls = resources(HTML)
    assert urls, "в index.html не найдено ни одного скрипта или стиля"
    for url in urls:
        assert not re.match(r"(https?:)?//", url), f"внешний ресурс: {url}"
        assert (ROOT / url).is_file(), f"нет файла {url}"


def test_page_has_no_inline_scripts_styles_or_handlers():
    assert inline_code(HTML) == []


@pytest.mark.parametrize("html", [
    "<SCRIPT>alert(1)</SCRIPT>",
    '<Script type="module">run()</Script>',
    "<STYLE>body { color: red }</STYLE>",
    '<div STYLE="color: red">',
    '<button ONCLICK="run()">',
])
def test_inline_code_is_found_in_any_case(html):
    assert inline_code(html)


def test_scripts_with_src_are_not_inline_code():
    assert inline_code('<script src="js/app.js"></script><SCRIPT SRC="js/theme.js"></SCRIPT>') == []


def test_resources_are_found_in_any_case():
    html = '<SCRIPT SRC="https://cdn.example.com/x.js"></SCRIPT><LINK REL="stylesheet" HREF="//cdn.example.com/x.css">'
    assert resources(html) == ["https://cdn.example.com/x.js", "//cdn.example.com/x.css"]


def test_scripts_do_not_insert_inline_styles_or_handlers():
    for name, js in SCRIPTS.items():
        assert not re.search(r"""(?i)style\s*=\s*["']""", js), f"{name}: style=\"…\" в разметке"
        assert not re.search(r"""(?i)\son[a-z]+\s*=\s*["']""", js), f"{name}: обработчик события в разметке"
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
