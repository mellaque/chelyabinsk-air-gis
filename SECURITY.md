# Безопасность

## Как сообщить об уязвимости

Пожалуйста, не создавайте для этого публичный issue. Воспользуйтесь
[приватным сообщением об уязвимости](https://github.com/mellaque/chelyabinsk-air-gis/security/advisories/new)
(вкладка **Security → Report a vulnerability**). Постараюсь ответить в течение недели.

## Что делается автоматически

| Мера | Где |
|---|---|
| Сканирование зависимостей, Docker-образов, секретов и конфигурации (Trivy) | `.github/workflows/security.yml`, при каждом PR и раз в неделю |
| Статический анализ Python, JavaScript и workflow (CodeQL) | `.github/workflows/security.yml` |
| Образ с критической уязвимостью, для которой есть исправление, не проходит CI | `.github/workflows/ci.yml`, job Docker |
| Обновления зависимостей и actions | Dependabot, раз в месяц |
| Все actions закреплены по хешу коммита, у job минимальные права | `.github/workflows/*.yml` |
| Workflow проверяют actionlint и zizmor, shell-скрипты — shellcheck | `.github/workflows/ci.yml`, job «Линтеры» |
| Образы подписаны (Sigstore cosign), к ним приложены SBOM и provenance | GitHub Container Registry |
| Публикуется ровно проверенный образ: digest проходит smoke-тест и Trivy, подписывается и только потом получает теги | `.github/workflows/ci.yml`, job публикации |
| Базовые образы обновляет Dependabot, новые версии — не раньше чем через 7 дней после выхода | `.github/dependabot.yml` |
| Контейнер сайта: nginx не от root, файловая система только для чтения, без capabilities | `Dockerfile`, `compose.yaml` |
| Страница: библиотеки свои (`vendor/` побайтно совпадает с пакетами npm), CSP запрещает чужой и встроенный код | `index.html`, `scripts/vendor_frontend.py`, тесты |

## Политика по уязвимостям

- **Образы**: в отчёт попадают уязвимости уровня High и Critical, для которых уже вышло исправление.
  Уязвимости без исправления в пакетах базовых образов (Debian, Alpine) кодом проекта устранить нельзя —
  они закрываются обновлением базового образа, которое CI подхватывает при пересборке.
- **Critical с исправлением** — блокирует CI (job Docker).
- **Репозиторий** (зависимости Python и библиотеки фронтенда из `package-lock.json`, секреты,
  конфигурация) — отчёт по всем уровням.
- Замечания, признанные ложными или приемлемыми, закрываются во вкладке Security
  с указанием причины — так видно, что они рассмотрены.

## Проверка подписи образа

```bash
cosign verify ghcr.io/mellaque/chelyabinsk-air-gis:latest \
  --certificate-identity-regexp '^https://github.com/mellaque/chelyabinsk-air-gis/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Команда подтверждает, что образ собран workflow этого репозитория на GitHub Actions
и не изменялся после сборки.
