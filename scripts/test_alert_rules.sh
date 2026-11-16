#!/bin/sh
# Проверка правил алертов Prometheus: синтаксис (promtool check rules) и тесты (promtool test rules).
#
#   sh scripts/test_alert_rules.sh
#
# promtool берётся из PATH, а если его нет — из образа Prometheus, который работает на сервере
# (версия и digest — в ansible/roles/monitoring/defaults/main.yml; нужен Docker).
# В CI версия promtool из PATH обязана совпадать с версией образа: иначе правила проверялись бы
# не той программой, которая будет их выполнять.
set -eu

cd "$(dirname "$0")/.."

role=ansible/roles/monitoring
rules=$role/files/prometheus/rules
tests=$role/tests/rules

image=$(sed -n 's/^monitoring_prometheus_image:[[:space:]]*//p' "$role/defaults/main.yml")
version=$(printf '%s\n' "$image" | sed -n 's/^[^:]*:v\([0-9][0-9.]*\)@sha256:[0-9a-f]\{64\}$/\1/p')
if [ -z "$version" ]; then
    echo "Не удалось прочитать образ Prometheus из $role/defaults/main.yml: '$image'" >&2
    exit 1
fi

if command -v promtool >/dev/null 2>&1; then
    found=$(promtool --version 2>&1 | sed -n 's/^promtool, version \([0-9][0-9.]*\).*/\1/p')
    if [ "$found" != "$version" ]; then
        echo "promtool версии '$found', а на сервере работает Prometheus $version" >&2
        if [ -n "${CI:-}" ]; then
            exit 1
        fi
    fi
    run() { promtool "$@"; }
elif command -v docker >/dev/null 2>&1; then
    echo "promtool не установлен — запускается из образа $image"
    run() {
        docker run --rm --network none --entrypoint /bin/promtool \
            --volume "$PWD/$role:/src/$role:ro" --workdir /src "$image" "$@"
    }
else
    echo "Нужен promtool (brew install prometheus) или Docker" >&2
    exit 1
fi

# Без кавычек намеренно: каждый файл — отдельный аргумент
# shellcheck disable=SC2086
run check rules $rules/*.yml
# shellcheck disable=SC2086
run test rules $tests/*_test.yml
