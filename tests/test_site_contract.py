"""Контракт между частями проекта: вещества на странице, в конфиге и в данных совпадают."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def app_substances() -> list[str]:
    """Ключи config.substances из js/app.js, в порядке объявления."""
    js = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    block = js[js.index("    substances: {"):]
    block = block[: block.index("\n    },\n")]
    return re.findall(r"^ {8}(\w+): \{", block, flags=re.M)


def config_substances() -> list[str]:
    return list(json.loads((ROOT / "config" / "substances.json").read_text(encoding="utf-8"))["substances"])


def test_app_and_config_list_the_same_substances_in_the_same_order():
    assert app_substances() == config_substances()


def test_default_substance_exists():
    js = (ROOT / "js" / "app.js").read_text(encoding="utf-8")
    default = re.search(r"defaultSubstance: '(\w+)'", js).group(1)
    assert default in config_substances()


def test_data_units_match_config():
    cfg = json.loads((ROOT / "config" / "substances.json").read_text(encoding="utf-8"))["substances"]
    for key, item in cfg.items():
        path = ROOT / "data" / f"{key}_data.json"
        if path.exists():            # отсутствие файла ловит scripts/validate_data.py
            assert json.loads(path.read_text(encoding="utf-8"))["units"] == item["units"], key


def test_select_is_filled_by_script():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    assert "<option" not in html.split('id="substance"', 1)[1].split("</select>", 1)[0]
