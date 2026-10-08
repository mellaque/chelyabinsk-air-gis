# syntax=docker/dockerfile:1

# ---------- Этап 1: проверка данных ----------
# Если в data/ лежит файл неправильного формата, образ просто не соберётся.
FROM python:3.12-slim AS validate
WORKDIR /app
COPY scripts/validate_data.py scripts/prepare_region.py scripts/
COPY config/ config/
COPY data/*.json data/region.geojson data/
RUN python scripts/validate_data.py

# ---------- Этап 2: веб-сервер ----------
# nginx-unprivileged работает от непривилегированного пользователя и слушает порт 8080
FROM nginxinc/nginx-unprivileged:1.30-alpine-slim

LABEL org.opencontainers.image.title="chelyabinsk-air-gis" \
      org.opencontainers.image.description="Веб-ГИС: концентрации HNO₃, CO, H₂O, O₃ над Челябинской областью по спутниковым данным NASA" \
      org.opencontainers.image.source="https://github.com/mellaque/chelyabinsk-air-gis" \
      org.opencontainers.image.licenses="MIT"

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
# Данные берём из первого этапа — то есть именно те, что прошли проверку
COPY --from=validate /app/data/ /usr/share/nginx/html/data/

# Базовый образ и так работает от пользователя nginx (UID 101); указываем явно —
# так видно из Dockerfile и так ожидают сканеры (Trivy DS-0002)
USER 101

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --start-interval=2s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
