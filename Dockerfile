# syntax=docker/dockerfile:1

# ---------- Этап 1: проверка данных ----------
# Если в data/ лежит файл неправильного формата, образ просто не соберётся.
FROM python:3.12-slim@sha256:191083cdf6c7bda8c76158983163ead5d5cf7b77cf3033e805bb0f5296f51b4b AS validate
WORKDIR /app
COPY scripts/validate_data.py scripts/prepare_region.py scripts/
COPY config/ config/
COPY data/*.json data/region.geojson data/
RUN python scripts/validate_data.py

# ---------- Этап 2: веб-сервер ----------
# nginx-unprivileged работает от непривилегированного пользователя и слушает порт 8080
FROM nginxinc/nginx-unprivileged:1.31-alpine-slim@sha256:a8cb0f33d51fa107c96fd2bd3a71aaf564ec131e9d2bdf8700944f0ed8b170d7

LABEL org.opencontainers.image.title="chelyabinsk-air-gis" \
      org.opencontainers.image.description="Веб-ГИС: NO₂, SO₂, CO, O₃, формальдегид, HNO₃ и водяной пар над Челябинской областью по реанализу NASA TROPESS" \
      org.opencontainers.image.source="https://github.com/mellaque/chelyabinsk-air-gis" \
      org.opencontainers.image.licenses="MIT"

# Временная заплатка до пересборки базового образа. Исправления musl (CVE-2026-107891) и zlib
# (CVE-2026-85091) уже есть в репозитории Alpine, а образ nginx-unprivileged с ними ещё не вышел —
# новый digest принести нечего. Обновляются только эти пакеты, остальное — как в базовом образе.
# Когда Dependabot принесёт digest с исправленными пакетами, команда ничего не изменит — тогда
# этот блок удалить (Trivy в Security покажет, нужен ли он ещё).
USER 0
RUN apk upgrade --no-cache musl musl-utils zlib

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
COPY vendor/ /usr/share/nginx/html/vendor/
# Данные берём из первого этапа — то есть именно те, что прошли проверку
COPY --from=validate /app/data/ /usr/share/nginx/html/data/

# Работаем от пользователя nginx (UID 101), как в базовом образе: выше для обновления пакетов
# понадобился root. Указано явно — так видно из Dockerfile и так ожидают сканеры (Trivy DS-0002)
USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --start-interval=2s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
