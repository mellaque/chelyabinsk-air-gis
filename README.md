# Веб-ГИС мониторинга качества атмосферного воздуха по спутниковым данным

[![CI](https://github.com/mellaque/chelyabinsk-air-gis/actions/workflows/ci.yml/badge.svg)](https://github.com/mellaque/chelyabinsk-air-gis/actions/workflows/ci.yml)

Интерактивная карта концентраций HNO₃, CO, H₂O и O₃ над Челябинской областью
по данным спутникового мониторинга и химического реанализа NASA.

**Демо:** <https://mellaque.github.io/chelyabinsk-air-gis/>

Проект выполнен как выпускная квалификационная работа (бакалавриат, УУНиТ).

> **Статус:** проект развивается после защиты. Версия в том виде, в каком она защищалась, —
> тег [`v1.0-thesis`](https://github.com/mellaque/chelyabinsk-air-gis/tree/v1.0-thesis).
> Что изменилось — см. [Исправлено после ВКР](#исправлено-после-вкр).

![Скриншот](docs/screenshot.webp)

## Возможности

- карта с маркерами городов (Челябинск, Магнитогорск, Златоуст, Миасс, Копейск, Озёрск) и границей области;
- выбор вещества, года, месяца и уровня высоты (уровни давления в гПа);
- анимация по годам, месяцам и уровням;
- график концентраций по городам (Chart.js);
- пропуски в данных показываются серым, а не как нулевая концентрация;
- подсказки с названиями районов, предупреждение о непроверенных данных;
- светлая и тёмная тема, переключение картографических подложек.

## Стек

HTML, CSS, JavaScript, [Leaflet](https://leafletjs.com/), [Chart.js](https://www.chartjs.org/).
Обработка данных — Python (netCDF4, NumPy). Тесты — pytest, линтер — Ruff, CI — GitHub Actions.
Развёртывание — Docker, nginx (непривилегированный образ), Docker Compose.

## Запуск

### Готовый образ

Образ публикуется в GitHub Container Registry при каждом изменении `main`:

```bash
docker run --rm -p 8080:8080 ghcr.io/mellaque/chelyabinsk-air-gis:latest
```

Сайт откроется на <http://localhost:8080>. Конкретную версию можно взять по тегу: `:2.0.0`, `:sha-<коммит>`.

### Сборка из исходников в Docker

Нужен [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS) или Docker Engine (Linux).

```bash
git clone https://github.com/mellaque/chelyabinsk-air-gis.git
cd chelyabinsk-air-gis
docker compose up -d --build
```

Сайт откроется на <http://localhost:8080>. Остановить: `docker compose down`.

Контейнер работает с минимальными правами: nginx запущен не от root, файловая система только
для чтения, без Linux capabilities. Данные отдаются со сжатием gzip, а браузер при каждом
открытии сверяет их с сервером (ответ 304, если файл не менялся).

### Без Docker

Браузер не загружает JSON-файлы со страницы, открытой напрямую (`file://`),
поэтому нужен любой локальный веб-сервер.

```bash
git clone https://github.com/mellaque/chelyabinsk-air-gis.git
cd chelyabinsk-air-gis
python -m http.server 8000
```

Затем открыть <http://localhost:8000>.

Альтернатива — расширение **Live Server** в VS Code: ПКМ по `index.html` → «Open with Live Server».

## Обработка данных

Готовые JSON уже лежат в `data/`, поэтому для запуска карты этот шаг не нужен.
Чтобы пересобрать данные из исходных NetCDF:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# файлы TRPSCRHNO3M3D (*.nc) положить в data/raw/hno3/
python scripts/process_tcr2.py --input data/raw/hno3 --substance hno3 --units ppb --output data/hno3_data.json

pytest                              # тесты
```

То же самое без установки Python — в контейнере:

```bash
docker compose run --rm pipeline
```

Скрипт сам определяет год и месяц по данным внутри файла, пропускает повторно скачанные файлы
и останавливается, если для одного года найдены два разных файла. Города задаются
в [`config/cities.json`](config/cities.json), формат результата описан в
[`docs/data-format.md`](docs/data-format.md).

## Разработка, CI и CD

Весь конвейер описан в [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
При каждом pull request и push в `main` запускаются проверки:

| Проверка | Что делает |
|---|---|
| **Ruff** | стиль кода и типичные ошибки в Python |
| **pytest** (Python 3.12 и 3.14) | тесты пайплайна NetCDF → JSON и проверки данных на синтетических файлах |
| **Проверка данных** | `scripts/validate_data.py`: все `data/*.json` в актуальном формате, размерности совпадают, нет NaN и отрицательных значений, у проверенных данных указан источник, в `region.geojson` нет битой кодировки |
| **Фронтенд** | синтаксис `js/app.js`, подключённые в `index.html` файлы существуют |
| **Docker** | hadolint проверяет Dockerfile, оба образа собираются, контейнер стартует с ограниченными правами и становится healthy, smoke-тест (`scripts/smoke_test.sh`) проверяет страницы, данные, сжатие и заголовки |

Если все проверки прошли и изменения попали в `main`, выполняется публикация:

| Что | Куда |
|---|---|
| Сайт | GitHub Pages — <https://mellaque.github.io/chelyabinsk-air-gis/>, после деплоя проверяется, что страница и данные доступны |
| Образ сайта | `ghcr.io/mellaque/chelyabinsk-air-gis` — теги `latest` и `sha-<коммит>` |
| Образ пайплайна | `ghcr.io/mellaque/chelyabinsk-air-gis-pipeline` |

Тег вида `v2.0.0` публикует образы с номером версии (`:2.0.0`, `:2.0`).
В `main` код попадает только через pull request с зелёными проверками (ruleset ветки).

Проверки локально:

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
python scripts/validate_data.py
```

Обновления зависимостей и версий actions раз в месяц предлагает Dependabot.

## Структура

```
├── index.html                  # страница приложения
├── Dockerfile                  # образ сайта: проверка данных → nginx
├── Dockerfile.pipeline         # образ пайплайна обработки NetCDF
├── compose.yaml                # запуск: docker compose up
├── deploy/nginx.conf           # конфигурация nginx
├── css/map-controls.css        # стили
├── js/app.js                   # карта, график, анимации
├── config/cities.json          # города и их координаты
├── data/
│   ├── hno3_data.json          # HNO₃: 6 городов, 2011–2021, 27 уровней
│   ├── co_data.json            # CO, H₂O, O₃ — данные версии ВКР (не проверены)
│   ├── h2o_data.json
│   ├── o3_data.json
│   ├── region.geojson          # граница области и районов
│   └── raw/                    # исходные NetCDF (не хранятся в git)
├── scripts/
│   ├── process_tcr2.py         # NetCDF (TCR-2) → JSON
│   ├── validate_data.py        # проверка формата данных (CI и сборка образа)
│   ├── smoke_test.sh           # проверка запущенного сайта
│   ├── prepare_region.py       # подготовка границ из выгрузки OSM
│   └── legacy/                 # скрипты версии ВКР
├── tests/                      # pytest
├── docs/data-format.md         # описание формата данных
├── .github/
│   ├── workflows/ci.yml        # CI/CD: проверки, публикация образов и сайта
│   └── dependabot.yml          # автообновление зависимостей
└── pyproject.toml              # настройки Ruff и pytest
```

## Данные

| Вещество | Источник |
|---|---|
| HNO₃ | TROPESS Chemical Reanalysis (TCR-2), продукт `TRPSCRHNO3M3D`, NASA JPL — [doi:10.5067/0VC7M1P01TQ7](https://doi.org/10.5067/0VC7M1P01TQ7) |
| CO, H₂O, O₃ | Aura MLS (Microwave Limb Sounder), NASA — данные версии ВКР, исходные файлы не сохранились |

Исходные файлы NetCDF не хранятся в репозитории (около 45 МБ на файл).
Данные NASA распространяются свободно, для скачивания нужна бесплатная учётная запись
[NASA Earthdata](https://urs.earthdata.nasa.gov/).

Картографическая основа и границы административных единиц (`region.geojson`) — © участники
[OpenStreetMap](https://www.openstreetmap.org/copyright), лицензия [ODbL](https://opendatacommons.org/licenses/odbl/).
Границы взяты из выгрузки OSM в shape-файлах проекта [ГИС-Лаб](http://gis-lab.info/projects/osmshp/)
и конвертированы в GeoJSON в QGIS; затем обработаны скриптом `scripts/prepare_region.py`
(исправлена кодировка названий, оставлены область и районы).

## Исправлено после ВКР

При повторном разборе проекта в версии ВКР нашлись ошибки. Что с ними сделано:

| Проблема в версии ВКР | Сейчас |
|---|---|
| Год вычислялся по номеру файла — все данные HNO₃ сдвинуты на год назад | Год и месяц читаются из переменной времени в файле |
| Файл за 2021 г. обработан дважды, «2022 г.» был его копией | Повторы определяются по SHA-256 и пропускаются |
| Пропуски (уровни ниже поверхности земли) записаны как `0` | Пропуски — `null`, на карте серые маркеры |
| Все значения подписаны как ppm, шкала не соответствовала данным | Единицы берутся из файла (HNO₃ — ppb), шкала строится по данным выбранного уровня |
| Кнопки анимации по годам и уровням не работали (обработчик добавлялся дважды) | Исправлено |
| Названия в `region.geojson` в неправильной кодировке, в файле лишние границы (вся РФ, УрФО) | Кодировка исправлена, оставлены область и районы; файл уменьшился с 1,8 до 0,85 МБ |
| Данные HNO₃ — 3,2 МБ в виде списка записей | Компактный формат, ~150 КБ |
| Ошибка в данных обнаруживалась только в браузере | CI проверяет формат данных при каждом изменении |

## Ограничения

- **CO, H₂O, O₃** — данные версии ВКР. Для CO и H₂O на промежуточном этапе значения разных регионов
  оказались одинаковыми, поэтому их принадлежность Челябинской области не гарантируется.
  В интерфейсе показывается предупреждение.
- **Пространственное разрешение.** Ячейка сетки TCR-2 — около 125 × 70 км, поэтому соседние города
  (Челябинск и Копейск, Миасс и Златоуст) получают одинаковые значения.
- **2022 год для HNO₃** в исходном наборе отсутствует.

## План развития

- [x] Новый пайплайн NetCDF → JSON без промежуточного Excel: год из метаданных, `null` для пропусков, явные единицы
- [x] Отображение пропусков на карте и корректные подписи единиц
- [x] Регион и список городов в конфигурационном файле
- [x] Тесты пайплайна
- [x] CI на GitHub Actions: Ruff, тесты, проверка данных и фронтенда при каждом push и PR
- [x] Docker и Docker Compose: образ сайта на nginx и образ пайплайна
- [x] Публикация образов в GitHub Container Registry
- [x] Деплой сайта на GitHub Pages
- [ ] Деплой контейнера на VPS (Ansible, обратный прокси с HTTPS)
- [ ] Скрипт автоматической загрузки данных с NASA Earthdata
- [ ] CO и O₃ из того же реанализа TCR-2 вместо непроверенных данных MLS

## Лицензия

Код — [MIT](LICENSE). Данные — по условиям их правообладателей (NASA, участники OpenStreetMap).
