#!/bin/sh
# Синхронизация зеркал (GitLab, GitVerse) с GitHub.
#
# GitHub — источник истины, зеркала — его точная копия: те же ветки и теги на тех же коммитах.
# Скрипт добавляет на зеркала недостающее, обновляет изменившееся и удаляет лишнее — в том числе
# ветки, которые GitHub удаляет сам после мержа pull request.
#
#   sh scripts/sync_mirrors.sh           синхронизировать
#   sh scripts/sync_mirrors.sh --check   только показать расхождения; код выхода 1, если они есть
#   sh scripts/sync_mirrors.sh -h        эта справка
#
# Через алиас git короче (настраивается один раз в каждом клоне, работает и в PowerShell):
#   git config alias.mirrors '!sh scripts/sync_mirrors.sh'
#   git mirrors --check
#   git mirrors
#
# Зеркала — только для чтения: то, что запушено прямо в зеркало, будет перезаписано или удалено,
# как при git push --mirror. Посмотреть заранее — --check (строки «перезапись» и «удаление»).
#
# Защита:
#   - если с GitHub не пришло ни одной ветки, синхронизация не начинается: иначе удаление лишнего
#     стёрло бы зеркала целиком;
#   - одновременно в одном репозитории идёт только один запуск (блокировка .git/sync-mirrors.lock);
#   - локальные ветки и теги не меняются и на зеркала не попадают: состояние GitHub загружается
#     во временные ссылки refs/sync-mirrors/, которые удаляются после работы.
#
# Переменные окружения (для тестов и CI):
#   SOURCE   remote с источником истины, по умолчанию origin
#   MIRRORS  адреса зеркал через пробел, по умолчанию — GitLab и GitVerse этого проекта
#
# POSIX sh: bash 3.2 (macOS), Git Bash (Windows), dash (Ubuntu).
set -eu

SOURCE=${SOURCE:-origin}
NS=refs/sync-mirrors        # временные ссылки с состоянием GitHub

if [ "$#" -gt 1 ]; then
    echo "Лишние аргументы: $* (справка: -h)" >&2
    exit 2
fi
check_only=0
case "${1:-}" in
    "") ;;
    --check | --dry-run | -n) check_only=1 ;;
    -h | --help)
        awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"
        exit 0
        ;;
    *)
        echo "Неизвестный аргумент: $1 (справка: -h)" >&2
        exit 2
        ;;
esac

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "Запустите скрипт внутри клона репозитория" >&2
    exit 2
fi
if ! source_url=$(git remote get-url "$SOURCE" 2>/dev/null); then
    echo "В репозитории нет remote «$SOURCE»" >&2
    exit 2
fi

# Адрес в общем виде — без схемы, пользователя, «.git» и «/» в конце, в нижнем регистре:
# git@github.com:a/b.git, ssh://git@github.com/a/b и https://github.com/a/b → github.com/a/b
normalize() {
    printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]' \
        | sed -e 's#/*$##' -e 's#\.git$##' -e 's#^[a-z+]*://##' -e 's#^[^@/]*@##' -e 's#:#/#'
}
source_id=$(normalize "$source_url")

# Зеркала по умолчанию — только когда источник именно этот репозиторий на GitHub. Иначе клон
# с зеркала или копия проекта перезаписали бы настоящие зеркала своими ветками.
if [ -z "${MIRRORS+set}" ]; then
    if [ "$source_id" != github.com/mellaque/chelyabinsk-air-gis ]; then
        echo "Источник $source_url — не репозиторий проекта на GitHub: укажите зеркала в MIRRORS" >&2
        exit 2
    fi
    MIRRORS="git@gitlab.com:mellaque/chelyabinsk-air-gis.git git@gitverse.ru:mellaque/chelyabinsk-air-gis.git"
fi
mirror_count=0
for url in $MIRRORS; do
    mirror_count=$((mirror_count + 1))
    # Зеркала перезаписываются принудительно, поэтому источник и GitHub зеркалом быть не могут
    case $(normalize "$url") in
        "$source_id" | github.com/*)
            echo "Адрес $url — источник или GitHub, а не зеркало: проверьте MIRRORS" >&2
            exit 2
            ;;
    esac
done
if [ "$mirror_count" = 0 ]; then
    echo "Не задано ни одного зеркала: переменная MIRRORS пуста" >&2
    exit 2
fi

# Строки списка через пробел: "main dev"
words() { printf '%s\n' "$1" | tr '\n' ' ' | sed 's/ *$//'; }
# Число непустых строк
count() { printf '%s\n' "$1" | grep -c . || true; }
# Удалить временные ссылки
cleanup() { git for-each-ref --format='delete %(refname)' "$NS/" | git update-ref --no-deref --stdin; }

# Блокировка: второй запуск, начавшись посреди первого, удалил бы его временные ссылки,
# и первый отправил бы на зеркала пустой список — с удалением всего лишнего.
lock="$(git rev-parse --git-common-dir)/sync-mirrors.lock"
locked=0
finish() {
    if [ "$locked" = 1 ]; then
        cleanup || echo "Не удалось удалить временные ссылки $NS/ (удалятся при следующем запуске)" >&2
        rmdir "$lock" 2>/dev/null || :
    fi
}
trap finish EXIT
trap 'exit 130' INT     # dash без этого не выполняет finish при Ctrl-C
trap 'exit 143' TERM
trap 'exit 129' HUP

if ! mkdir "$lock" 2>/dev/null; then
    echo "Синхронизация уже идёт в этом репозитории (блокировка $lock)." >&2
    echo "Если другого запуска нет — прошлый был прерван, — удалите эту папку и повторите." >&2
    exit 1
fi
locked=1

# Остатки прерванного запуска не должны попасть на зеркала
if ! cleanup || [ -n "$(git for-each-ref "$NS/")" ]; then
    echo "Не удалось очистить временные ссылки $NS/ — синхронизация остановлена" >&2
    exit 1
fi

echo "Источник: $source_url"

# Ветки и теги GitHub — во временные ссылки. Загрузка по адресу, а не по имени remote, — так
# не меняются refs/remotes/; --no-tags и --no-prune — чтобы не задеть локальные теги.
if ! git fetch --quiet --no-tags --no-prune "$source_url" \
    "+refs/heads/*:$NS/heads/*" "+refs/tags/*:$NS/tags/*"; then
    echo "Не удалось получить ветки и теги с $source_url — зеркала не тронуты" >&2
    exit 1
fi

branches=$(git for-each-ref --format='%(refname:lstrip=3)' "$NS/heads/")
tags=$(git for-each-ref --format='%(refname:lstrip=3)' "$NS/tags/")

# Защита от пустого списка: удаление лишнего (--prune) стёрло бы на зеркалах всё
if [ -z "$branches" ]; then
    echo "На $source_url не найдено ни одной ветки — синхронизация остановлена, зеркала не тронуты" >&2
    exit 1
fi

branch_count=$(count "$branches")
if [ "$branch_count" -le 10 ]; then
    echo "На GitHub: веток $branch_count ($(words "$branches")), тегов $(count "$tags")"
else
    echo "На GitHub: веток $branch_count, тегов $(count "$tags")"
fi

tab=$(printf '\t')
errors=0
drift=0

for url in $MIRRORS; do
    echo
    echo "== $url"

    set -- --porcelain --prune --no-follow-tags
    if [ "$check_only" = 1 ]; then
        set -- "$@" --dry-run
    fi
    # «+» — зеркало приводится к GitHub, даже если ветку там переписали (force-push на GitHub,
    # ребейз Dependabot). --prune удаляет на зеркале ветки и теги, которых нет на GitHub.
    # --no-follow-tags — чтобы push.followTags=true не отправил на зеркала локальные теги.
    if out=$(git push "$@" "$url" "+$NS/heads/*:refs/heads/*" "+$NS/tags/*:refs/tags/*"); then
        pushed=1
    else
        pushed=0
    fi

    changes=0
    rejected=0
    delete_refused=0
    update_refused=0
    same=""
    # Формат --porcelain: <флаг> TAB <откуда>:<куда> TAB <итог>
    while IFS=$tab read -r flag refs summary; do
        case $flag in
            ' ' | '+' | '-' | '*' | '!' | '=') ;;
            *) continue ;;   # строки «To …» и «Done»
        esac
        dst=${refs#*:}
        case $dst in
            refs/heads/*) what="ветка ${dst#refs/heads/}" ;;
            refs/tags/*) what="тег ${dst#refs/tags/}" ;;
            *) what=$dst ;;
        esac
        case $flag in
            '=') same="$same ${dst#refs/*/}" ;;
            '*') echo "  + добавление: $what"; changes=$((changes + 1)) ;;
            ' ') echo "  ~ обновление: $what ($summary)"; changes=$((changes + 1)) ;;
            '+') echo "  ~ перезапись: $what ($summary)"; changes=$((changes + 1)) ;;
            '-') echo "  - удаление:   $what"; changes=$((changes + 1)) ;;
            *)
                echo "  ! отклонено:  $what — $summary"
                rejected=$((rejected + 1))
                case $refs in
                    :*) delete_refused=1 ;;
                    *) update_refused=1 ;;
                esac
                ;;
        esac
    done <<EOF
$out
EOF
    if [ -n "$same" ]; then
        echo "  = без изменений:$same"
    fi

    if [ "$delete_refused" = 1 ]; then
        echo "  -> зеркало не даёт удалить ветку: обычно это ветка по умолчанию или защищённая."
        echo "     Сделайте веткой по умолчанию main, снимите защиту в настройках зеркала и повторите."
    fi
    if [ "$update_refused" = 1 ]; then
        echo "  -> зеркало не приняло обновление: обычно мешает защита ветки или тега (запрет force-push)"
        echo "     в настройках зеркала. Причина — в сообщениях git выше."
    fi

    if [ "$rejected" -gt 0 ]; then
        echo "  -> ОШИБКА: зеркало отклонило изменений: $rejected"
        errors=$((errors + 1))
    elif [ "$pushed" = 0 ]; then
        echo "  -> ОШИБКА: зеркало недоступно или push не прошёл (сообщение git — выше)"
        errors=$((errors + 1))
    elif [ "$changes" = 0 ]; then
        echo "  -> совпадает с GitHub"
    elif [ "$check_only" = 1 ]; then
        echo "  -> не совпадает с GitHub, изменений: $changes"
        drift=$((drift + 1))
    else
        echo "  -> синхронизировано, изменений: $changes"
    fi
done

echo
if [ "$errors" -gt 0 ]; then
    echo "Есть ошибки — подробности выше." >&2
    exit 1
elif [ "$drift" -gt 0 ]; then
    echo "Есть расхождения. Синхронизировать: git mirrors (или sh scripts/sync_mirrors.sh)."
    exit 1
fi
echo "Зеркала совпадают с GitHub."
