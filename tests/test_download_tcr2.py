"""Тесты загрузчика на локальном «фальшивом NASA».

Сервер имитирует три части настоящей схемы:
  /search/granules.json — каталог CMR со списком файлов;
  /data/<файл>          — сервер GES DISC: проверяет токен и перенаправляет в хранилище;
  /bucket/<файл>        — облачное хранилище на ДРУГОМ хосте (localhost вместо 127.0.0.1),
                          куда токен попадать не должен.
"""

import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import download_tcr2 as d  # noqa: E402

TOKEN = "good-token"
YEARS = [2005, 2006, 2007]
SIZE = 300_000


def fake_netcdf(year: int) -> bytes:
    body = bytes((year + i) % 251 for i in range(SIZE - 8))
    return b"\x89HDF\r\n\x1a\n" + body


class FakeNasa(BaseHTTPRequestHandler):
    state: dict = {}

    def log_message(self, *args):  # тишина в выводе тестов
        pass

    def _send(self, code, body=b"", ctype="application/octet-stream", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        st = self.state
        url = urlparse(self.path)
        st["requests"].append((url.path, dict(self.headers)))

        if url.path == "/search/granules.json":
            if st.get("cmr_fail", 0) > 0:
                st["cmr_fail"] -= 1
                return self._send(503, b"busy", "text/plain")
            q = parse_qs(url.query)
            assert q["short_name"] == ["TESTPROD"]
            entries = [{
                "time_start": f"{y}-01-01T00:00:00.000Z",
                "granule_size": str(SIZE / 1024 / 1024),
                "links": [
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": f"s3://bucket/test_{y}.nc"},
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/data#", "href": f"{st['data_base']}/data/test_{y}.nc"},
                    {"rel": "http://esipfed.org/ns/fedsearch/1.1/metadata#",
                     "href": f"{st['data_base']}/data/test_{y}.nc.dmrpp"},
                ],
            } for y in YEARS]
            return self._send(200, json.dumps({"feed": {"entry": entries}}).encode(), "application/json")

        if url.path.startswith("/data/"):
            name = url.path.rsplit("/", 1)[-1]
            if st.get("login_page"):
                return self._send(200, b"<html>Earthdata Login</html>", "text/html; charset=utf-8")
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, b"Unauthorized", "text/plain")
            # как в GES DISC: редирект на подписанную ссылку в хранилище на другом хосте
            return self._send(307, extra={"Location": f"{st['bucket_base']}/bucket/{name}?signature=abc"})

        if url.path.startswith("/bucket/"):
            name = url.path.rsplit("/", 1)[-1]
            year = int(name.split("_")[1].split(".")[0])
            data = fake_netcdf(year)
            if st.get("fail_503", 0) > 0:
                st["fail_503"] -= 1
                return self._send(503, b"busy", "text/plain", {"Retry-After": "0"})
            rng = self.headers.get("Range")
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
                chunk = data[start:]
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                self.send_header("Content-Length", str(len(chunk)))
                self.end_headers()
                self.wfile.write(chunk)
                return
            if st.get("truncate", 0) > 0:
                # обрыв связи: обещаем весь файл, отдаём треть и закрываем соединение
                st["truncate"] -= 1
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data[: len(data) // 3])
                self.wfile.flush()
                self.close_connection = True
                return
            return self._send(200, data)

        self._send(404, b"not found", "text/plain")


@pytest.fixture
def nasa(tmp_path, monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeNasa)
    port = server.server_address[1]
    FakeNasa.state = {
        "requests": [],
        "data_base": f"http://127.0.0.1:{port}",
        "bucket_base": f"http://localhost:{port}",      # другой хост — как облачное хранилище
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    config = tmp_path / "substances.json"
    config.write_text(json.dumps({"substances": {"xx": {"product": "TESTPROD", "version": "1", "units": "ppb"}}}),
                      encoding="utf-8")
    monkeypatch.setattr(d.time, "sleep", lambda *_: None)     # без пауз между повторами
    monkeypatch.setattr(d, "CHUNK", 16 * 1024)                # тестовые файлы маленькие — читаем мелкими кусками
    monkeypatch.delenv(d.TOKEN_ENV, raising=False)

    def run(*extra):
        return d.main(["--substance", "xx", "--config", str(config), "--output", str(tmp_path / "raw"),
                       "--cmr-url", f"http://127.0.0.1:{port}/search/granules.json", *extra])

    yield FakeNasa.state, run, tmp_path / "raw"
    server.shutdown()


def requests_to(state, prefix):
    return [h for path, h in state["requests"] if path.startswith(prefix)]


def test_parse_years():
    assert d.parse_years("2005-2007") == [2005, 2006, 2007]
    assert d.parse_years("2011, 2009") == [2009, 2011]
    assert d.parse_years("2019") == [2019]
    with pytest.raises(ValueError):
        d.parse_years("2010-2005")


def test_dry_run_needs_no_token(nasa, capsys):
    state, run, raw = nasa
    assert run("--dry-run") == 0
    out = capsys.readouterr().out
    assert "test_2005.nc" in out and "test_2007.nc" in out
    assert ".dmrpp" not in out and "s3://" not in out
    assert not raw.exists()


def test_download_sends_token_only_to_nasa(nasa, monkeypatch):
    state, run, raw = nasa
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    assert run() == 0
    for y in YEARS:
        assert (raw / f"test_{y}.nc").read_bytes() == fake_netcdf(y)
    assert not list(raw.glob("*.part"))
    assert all(h.get("Authorization") == f"Bearer {TOKEN}" for h in requests_to(state, "/data/"))
    # главное: токен не ушёл в «облачное хранилище» на другом хосте
    assert all("Authorization" not in h for h in requests_to(state, "/bucket/"))


def test_second_run_skips_downloaded(nasa, monkeypatch):
    state, run, raw = nasa
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    assert run() == 0
    before = len(requests_to(state, "/bucket/"))
    assert run() == 0
    assert len(requests_to(state, "/bucket/")) == before


def test_years_filter(nasa, monkeypatch):
    state, run, raw = nasa
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    assert run("--years", "2006") == 0
    assert sorted(p.name for p in raw.glob("*.nc")) == ["test_2006.nc"]


def test_missing_token(nasa, caplog):
    state, run, raw = nasa
    with caplog.at_level(logging.ERROR):
        assert run() == 1
    assert d.TOKEN_ENV in caplog.text
    assert not requests_to(state, "/data/")


def test_wrong_token(nasa, monkeypatch, caplog):
    state, run, raw = nasa
    monkeypatch.setenv(d.TOKEN_ENV, "expired")
    with caplog.at_level(logging.ERROR):
        assert run() == 1
    assert "HTTP 401" in caplog.text and "GESDISC" in caplog.text
    assert not list(raw.glob("*.nc"))


def test_login_page_instead_of_file(nasa, monkeypatch, caplog):
    state, run, raw = nasa
    state["login_page"] = True
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    with caplog.at_level(logging.ERROR):
        assert run() == 1
    assert "HTML" in caplog.text
    assert not list(raw.glob("*.nc"))


def test_resume_after_broken_connection(nasa, monkeypatch):
    state, run, raw = nasa
    state["truncate"] = 1
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    assert run("--years", "2005") == 0
    assert (raw / "test_2005.nc").read_bytes() == fake_netcdf(2005)
    ranges = [h.get("Range") for h in requests_to(state, "/bucket/")]
    assert ranges[0] is None and ranges[1].startswith("bytes=")   # вторая попытка — докачка


def test_retry_on_server_error(nasa, monkeypatch):
    state, run, raw = nasa
    state["fail_503"] = 2
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    assert run("--years", "2005") == 0
    assert (raw / "test_2005.nc").exists()


def test_warns_about_foreign_files(nasa, monkeypatch, caplog):
    state, run, raw = nasa
    raw.mkdir(parents=True)
    (raw / "file.nc").write_bytes(b"CDF\x01old")
    monkeypatch.setenv(d.TOKEN_ENV, TOKEN)
    with caplog.at_level(logging.WARNING):
        assert run("--years", "2005") == 0
    assert "file.nc" in caplog.text


def test_total_size_from_headers():
    class R:
        def __init__(self, code, headers):
            self.status_code, self.headers = code, headers
    assert d.total_size_from_headers(R(200, {"Content-Length": "100"})) == 100
    assert d.total_size_from_headers(R(206, {"Content-Range": "bytes 40-99/100"})) == 100
    assert d.total_size_from_headers(R(206, {"Content-Range": "bytes 40-99/*"})) is None


def test_catalog_retry(nasa, capsys):
    state, run, raw = nasa
    state["cmr_fail"] = 2                 # каталог дважды отвечает 503, потом нормально
    assert run("--dry-run") == 0
    assert "test_2005.nc" in capsys.readouterr().out


def test_catalog_gives_up(nasa, caplog):
    state, run, raw = nasa
    state["cmr_fail"] = 99
    with caplog.at_level(logging.ERROR):
        assert run("--dry-run") == 1
    assert "HTTP 503" in caplog.text
