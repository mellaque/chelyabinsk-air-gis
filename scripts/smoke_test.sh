#!/usr/bin/env bash
# Smoke-тест запущенного сайта: страница, скрипты и данные отдаются, заголовки на месте.
#   scripts/smoke_test.sh http://localhost:8080
set -uo pipefail

BASE="${1:-http://localhost:8080}"
failed=0

# check "сообщение при успехе" "сообщение при ошибке" команда [аргументы...]
check() {
    local ok_msg=$1 fail_msg=$2
    shift 2
    if "$@"; then
        echo "  ok   $ok_msg"
    else
        echo "  FAIL $fail_msg"
        failed=1
    fi
}

# Код ответа для пути
status() { curl -s -o /dev/null -w '%{http_code}' "$BASE$1"; }

# Значение заголовка ответа; третий аргумент — Accept-Encoding (по умолчанию без сжатия)
header() {
    curl -s -D - -o /dev/null -H "Accept-Encoding: ${3:-identity}" "$BASE$1" \
        | tr -d '\r' | grep -i "^$2:" | head -1 | cut -d' ' -f2-
}

# Тело ответа содержит строку
body_contains() { curl -s "$BASE$1" | grep -qF -- "$2"; }

echo "Проверяю $BASE"

echo "Файлы отдаются:"
for path in / /index.html /js/app.js /css/map-controls.css /healthz \
            /data/no2_data.json /data/so2_data.json /data/co_data.json /data/o3_data.json \
            /data/ch2o_data.json /data/hno3_data.json /data/h2o_data.json /data/region.geojson; do
    code=$(status "$path")
    check "$path → 200" "$path → $code (ожидался 200)" test "$code" = 200
done

echo "Лишнее не отдаётся:"
for path in /data/raw/ /.git/config /Dockerfile /compose.yaml /scripts/process_tcr2.py /нет-такого; do
    code=$(status "$path")
    check "$path → 404" "$path → $code (ожидался 404)" test "$code" = 404
done

echo "Содержимое:"
check "/healthz → ok" "/healthz не вернул ok" body_contains /healthz "ok"
check "index.html содержит карту" "в index.html нет #map" body_contains / '<div id="map">'
check "hno3_data.json в формате schema_version 2" "hno3_data.json не в формате 2" \
    body_contains /data/hno3_data.json '"schema_version":2'

echo "Заголовки:"
ct=$(header /data/region.geojson Content-Type)
check "region.geojson: Content-Type $ct" "region.geojson: Content-Type '$ct'" \
    test "${ct%%;*}" = "application/geo+json"
cc=$(header /data/hno3_data.json Cache-Control)
check "данные: Cache-Control no-cache" "данные: Cache-Control '$cc'" test "$cc" = "no-cache"
enc=$(header /data/hno3_data.json Content-Encoding gzip)
check "данные сжимаются gzip" "данные не сжимаются (Content-Encoding '$enc')" test "$enc" = "gzip"
nos=$(header / X-Content-Type-Options)
check "X-Content-Type-Options: nosniff" "нет X-Content-Type-Options" test "$nos" = "nosniff"
srv=$(header / Server)
check "версия сервера скрыта (Server: $srv)" "версия сервера видна: $srv" test "$srv" = "nginx"

if [ "$failed" -ne 0 ]; then
    echo "Smoke-тест НЕ пройден"
    exit 1
fi
echo "Smoke-тест пройден"
