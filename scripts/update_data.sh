#!/usr/bin/env bash
# Скачать исходные файлы NASA и пересобрать data/*.json для веществ из config/substances.json.
#
#   export EARTHDATA_TOKEN=<токен>
#   bash scripts/update_data.sh            # все вещества
#   bash scripts/update_data.sh co o3      # только указанные
#
# Уже скачанные файлы повторно не загружаются, поэтому повторный запуск быстрый.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ "$#" -gt 0 ]; then
    substances=("$@")
else
    # без mapfile — чтобы работало и в bash 3.2, который стоит в macOS по умолчанию
    substances=()
    while IFS= read -r s; do
        substances+=("$s")
    done < <(python3 -c 'import json; print("\n".join(json.load(open("config/substances.json"))["substances"]))')
fi

for s in "${substances[@]}"; do
    echo "===== $s: загрузка"
    python3 scripts/download_tcr2.py --substance "$s"
    echo "===== $s: обработка"
    python3 scripts/process_tcr2.py --input "data/raw/$s" --substance "$s" --output "data/${s}_data.json"
done

echo "===== проверка формата данных"
python3 scripts/validate_data.py
