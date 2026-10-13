"""Тесты синхронизации зеркал (scripts/sync_mirrors.sh) на локальных репозиториях.

Вместо GitHub, GitLab и GitVerse — три bare-репозитория во временной папке, рабочая копия
клонирована «с GitHub». Проверяется настоящий git push, без сети и учётных записей.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_mirrors.sh"

pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("sh") is None,
                                reason="нужны git и sh")

# Хук «защищённой ветки», как main в GitLab: перезапись истории (force-push) запрещена
PROTECTED_MAIN_HOOK = """#!/bin/sh
if [ "$1" = refs/heads/main ] && ! git merge-base --is-ancestor "$2" "$3"; then
    echo "You are not allowed to force push code to a protected branch on this project." >&2
    exit 1
fi
"""


class Hosts:
    """«GitHub», два зеркала и рабочая копия, клонированная с «GitHub»."""

    def __init__(self, tmp_path: Path):
        # Свой конфиг git вместо конфига разработчика: подпись коммитов, хуки и т. п. не мешают
        (tmp_path / ".gitconfig").write_text(
            "[user]\n\tname = test\n\temail = test@example.com\n[init]\n\tdefaultBranch = main\n",
            encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "MIRRORS"}
        self.env.update(HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path),
                        GIT_CONFIG_GLOBAL=str(tmp_path / ".gitconfig"), GIT_CONFIG_NOSYSTEM="1",
                        # только локальные репозитории: тесты не могут достучаться до настоящих зеркал
                        GIT_ALLOW_PROTOCOL="file")

        self.tmp = tmp_path
        self.github, self.gitlab, self.gitverse = (tmp_path / f"{name}.git"
                                                   for name in ("github", "gitlab", "gitverse"))
        for bare in (self.github, self.gitlab, self.gitverse):
            self.git(tmp_path, "init", "--quiet", "--bare", str(bare))
        self.work = tmp_path / "work"
        self.git(tmp_path, "clone", "--quiet", str(self.github), str(self.work))

    def git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True,
                                text=True, encoding="utf-8")
        assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
        return result.stdout

    def commit(self, message: str) -> None:
        self.git(self.work, "commit", "--quiet", "--allow-empty", "-m", message)

    def refs(self, repo: Path) -> dict[str, str]:
        """Ветки и теги репозитория: {ссылка: коммит}."""
        out = self.git(self.work, "ls-remote", "--heads", "--tags", "--refs", str(repo))
        return {ref: sha for sha, ref in (line.split("\t") for line in out.splitlines())}

    def push_directly(self, mirror: Path) -> str:
        """Коммит, запушенный прямо в main зеркала (мимо GitHub). Возвращает его хеш."""
        self.git(self.work, "switch", "--quiet", "--detach", "main")
        self.commit("прямой push в зеркало")
        self.git(self.work, "push", "--quiet", "--force", str(mirror), "HEAD:refs/heads/main")
        sha = self.git(self.work, "rev-parse", "HEAD").strip()
        self.git(self.work, "switch", "--quiet", "main")
        return sha

    def sync(self, *args: str, mirrors=None, **env: str) -> subprocess.CompletedProcess:
        run_env = dict(self.env, MIRRORS=" ".join(str(m) for m in (mirrors or (self.gitlab, self.gitverse))))
        run_env.update(env)
        return subprocess.run(["sh", str(SCRIPT), *args], cwd=self.work, env=run_env, capture_output=True,
                              text=True, encoding="utf-8")


@pytest.fixture
def hosts(tmp_path):
    """GitHub: main, ветка dependabot/…, теги v1.0 (лёгкий) и v2.0 (аннотированный).
    GitLab отстаёт и хранит ветку gitlab-ci, которую GitHub удалил после мержа. GitVerse пуст."""
    h = Hosts(tmp_path)
    h.commit("c1")
    h.git(h.work, "push", "--quiet", "origin", "main")
    h.git(h.work, "push", "--quiet", str(h.gitlab), "main", "main:refs/heads/gitlab-ci")
    h.git(h.work, "tag", "v1.0")
    h.commit("c2")
    h.git(h.work, "tag", "-a", "v2.0", "-m", "v2.0")
    h.git(h.work, "push", "--quiet", "origin", "main", "v1.0", "v2.0", "main:refs/heads/dependabot/pip/numpy")
    return h


def output(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def test_check_reports_differences_and_changes_nothing(hosts):
    before = hosts.refs(hosts.gitlab), hosts.refs(hosts.gitverse)
    result = hosts.sync("--check")
    assert result.returncode == 1, output(result)
    assert "удаление:   ветка gitlab-ci" in result.stdout
    assert "обновление: ветка main" in result.stdout
    assert "добавление: тег v2.0" in result.stdout
    assert (hosts.refs(hosts.gitlab), hosts.refs(hosts.gitverse)) == before


def test_sync_makes_mirrors_exact_copies(hosts):
    result = hosts.sync()
    assert result.returncode == 0, output(result)
    github = hosts.refs(hosts.github)
    assert hosts.refs(hosts.gitlab) == github
    assert hosts.refs(hosts.gitverse) == github
    assert hosts.sync("--check").returncode == 0


def test_deleted_on_github_is_deleted_on_mirrors(hosts):
    """Исходная проблема: GitHub сам удаляет ветку после мержа PR, а на зеркалах она оставалась."""
    assert hosts.sync().returncode == 0
    hosts.git(hosts.work, "push", "--quiet", "origin", "--delete", "dependabot/pip/numpy", "v1.0")
    result = hosts.sync()
    assert result.returncode == 0, output(result)
    for mirror in (hosts.gitlab, hosts.gitverse):
        assert hosts.refs(mirror) == hosts.refs(hosts.github)


def test_force_push_on_github_is_mirrored(hosts):
    """Ребейз ветки на GitHub (свой или Dependabot) — зеркала перезаписываются, а не застревают."""
    assert hosts.sync().returncode == 0
    hosts.git(hosts.work, "switch", "--quiet", "--detach", "main~1")
    hosts.commit("ветка после ребейза")
    hosts.git(hosts.work, "push", "--quiet", "--force", "origin", "HEAD:refs/heads/dependabot/pip/numpy")
    hosts.git(hosts.work, "switch", "--quiet", "main")

    assert "перезапись: ветка dependabot/pip/numpy" in hosts.sync("--check").stdout
    result = hosts.sync()
    assert result.returncode == 0, output(result)
    assert hosts.refs(hosts.gitlab) == hosts.refs(hosts.github)


def test_direct_push_to_mirror_is_overwritten(hosts):
    """Зеркала только для чтения: запушенное в них мимо GitHub перезаписывается."""
    assert hosts.sync().returncode == 0
    hosts.push_directly(hosts.gitverse)
    result = hosts.sync()
    assert result.returncode == 0, output(result)
    assert hosts.refs(hosts.gitverse) == hosts.refs(hosts.github)


def test_protected_branch_on_mirror_is_reported(hosts):
    """Зеркало запрещает force-push в main: ошибка, остальные ветки и второе зеркало обновлены."""
    assert hosts.sync().returncode == 0
    hook = hosts.gitlab / "hooks" / "update"
    hook.write_text(PROTECTED_MAIN_HOOK, encoding="utf-8")
    hook.chmod(0o755)
    mirror_main = hosts.push_directly(hosts.gitlab)
    hosts.commit("c3")
    hosts.git(hosts.work, "push", "--quiet", "origin", "main:refs/heads/dependabot/pip/numpy")

    result = hosts.sync()
    assert result.returncode == 1, output(result)
    assert "отклонено:  ветка main" in result.stdout
    gitlab = hosts.refs(hosts.gitlab)
    assert gitlab["refs/heads/main"] == mirror_main
    assert gitlab["refs/heads/dependabot/pip/numpy"] == hosts.refs(hosts.github)["refs/heads/dependabot/pip/numpy"]
    assert hosts.refs(hosts.gitverse) == hosts.refs(hosts.github)


def test_local_refs_are_not_pushed_and_not_changed(hosts):
    hosts.git(hosts.work, "config", "push.followTags", "true")   # отправил бы аннотированные теги
    hosts.git(hosts.work, "branch", "local-only")
    hosts.git(hosts.work, "tag", "-a", "local-tag", "-m", "только локально")
    before = hosts.git(hosts.work, "for-each-ref")
    assert hosts.sync().returncode == 0
    assert hosts.git(hosts.work, "for-each-ref") == before     # временные refs/sync-mirrors/ тоже убраны
    for mirror in (hosts.gitlab, hosts.gitverse):
        assert hosts.refs(mirror) == hosts.refs(hosts.github)


def test_unreachable_mirror_does_not_stop_others(hosts):
    result = hosts.sync(mirrors=[hosts.tmp / "missing.git", hosts.gitverse])
    assert result.returncode == 1, output(result)
    assert "недоступно" in result.stdout
    assert hosts.refs(hosts.gitverse) == hosts.refs(hosts.github)


def test_source_without_branches_stops_before_push(hosts):
    """Защита: при пустом списке веток удаление лишнего стёрло бы зеркала целиком."""
    empty = hosts.tmp / "empty.git"
    hosts.git(hosts.tmp, "init", "--quiet", "--bare", str(empty))
    hosts.git(hosts.work, "remote", "add", "empty", str(empty))
    before = hosts.refs(hosts.gitlab)
    result = hosts.sync(SOURCE="empty")
    assert result.returncode == 1, output(result)
    assert hosts.refs(hosts.gitlab) == before


def test_second_run_is_refused_while_first_runs(hosts):
    """Пока идёт один запуск, второй не начинается и не трогает чужие временные ссылки."""
    lock = hosts.work / ".git" / "sync-mirrors.lock"
    lock.mkdir()
    before = hosts.refs(hosts.gitlab)
    result = hosts.sync("--check")
    assert result.returncode == 1, output(result)
    assert "уже идёт" in result.stderr
    assert lock.is_dir()
    assert hosts.refs(hosts.gitlab) == before


def test_leftovers_of_interrupted_run_are_not_pushed(hosts):
    hosts.git(hosts.work, "update-ref", "refs/sync-mirrors/heads/leftover", "HEAD")
    assert hosts.sync().returncode == 0
    assert "refs/heads/leftover" not in hosts.refs(hosts.gitlab)
    assert hosts.git(hosts.work, "for-each-ref", "refs/sync-mirrors/") == ""


@pytest.mark.parametrize("source", [
    None,                                                       # локальный путь, как у всех тестов
    "git@github.com:mellaque/chelyabinsk-air-gis-v2.git",       # копия проекта
    "ssh://git@gitverse.ru/mellaque/chelyabinsk-air-gis.git",   # клон с зеркала
    "https://gitlab.com/mellaque/chelyabinsk-air-gis",
])
def test_default_mirrors_need_project_on_github_as_source(hosts, source):
    """Без MIRRORS скрипт пушит на настоящие зеркала проекта — но только из клона с GitHub,
    иначе чужие ветки перезаписали бы зеркала. Проверка срабатывает до обращения к сети."""
    if source:
        hosts.git(hosts.work, "remote", "set-url", "origin", source)
    env = {k: v for k, v in hosts.env.items() if k != "MIRRORS"}
    result = subprocess.run(["sh", str(SCRIPT), "--check"], cwd=hosts.work, env=env, capture_output=True,
                            text=True, encoding="utf-8")
    assert result.returncode == 2, output(result)
    assert "MIRRORS" in result.stderr


@pytest.mark.parametrize("mirror", [
    "{github}/",                                                # источник, записанный иначе
    "git@github.com:mellaque/chelyabinsk-air-gis.git",
    "https://GitHub.com/mellaque/other",
])
def test_source_and_github_are_never_mirrors(hosts, mirror):
    """Зеркала перезаписываются принудительно — GitHub среди них оказаться не должен."""
    result = hosts.sync(mirrors=[hosts.gitlab, mirror.format(github=hosts.github)])
    assert result.returncode == 2, output(result)
    assert hosts.refs(hosts.gitlab) != hosts.refs(hosts.github)   # даже первое зеркало не тронуто


@pytest.mark.parametrize("args", [["--bogus"], ["--check", "extra"]])
def test_bad_arguments(hosts, args):
    assert hosts.sync(*args).returncode == 2


def test_blank_mirrors_is_an_error(hosts):
    assert hosts.sync(MIRRORS=" ").returncode == 2
