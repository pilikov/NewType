# Daily-парсинг: отчёт на email и слияние на бой (Vercel)

После каждого ежедневного прогона на **pilikoff@gmail.com** приходит письмо с отчётом и ссылкой. По переходу по ссылке выполняется слияние ветки **crawl/daily** в **main** (слив данных на бой); Vercel при этом делает деплой с новыми данными.

## Что настроить

### 1. GitHub Secrets (репозиторий → Settings → Actions → Secrets)

| Secret | Описание |
|--------|----------|
| `RESEND_API_KEY` | Ключ API [Resend](https://resend.com) (отправка писем). Без него шаг отправки пропускается. |
| `PUBLISH_LINK` | Полная ссылка для «слить на бой», например: `https://ВАШ-САЙТ.vercel.app/api/publish-to-production?token=ВАШ_СЕКРЕТ`. Без неё в письме будет текст без кликабельной ссылки. |
| `PUBLISH_SECRET` | Тот же токен, что в `PUBLISH_LINK` (см. ниже). |

### 2. Vercel Environment Variables (проект → Settings → Environment Variables)

| Переменная | Значение | Среда |
|------------|----------|--------|
| `PUBLISH_SECRET` | Случайная строка (например из `openssl rand -hex 24`). Её же подставьте в `PUBLISH_LINK` в GitHub. | Production (и Preview при желании) |
| `PUBLISH_GITHUB_TOKEN` | GitHub PAT с правом **repo** (для merge). Создать: GitHub → Settings → Developer settings → Personal access tokens. | Production |
| `GITHUB_REPO` | Имя репозитория в формате `owner/repo`, например `username/Type-Parser`. | Production |

После добавления переменных сделайте повторный деплой, чтобы они подхватились.

### 3. Workflow permissions

В репозитории: **Settings → Actions → General → Workflow permissions** → **Read and write permissions**, чтобы workflow мог пушить в ветку `crawl/daily`.

## Поведение

1. **По расписанию** (ежедневно в 06:00 UTC) или по кнопке **Run workflow** выполняется прогон `python -m src.main --daily`.
2. Краулер пишет в **`data/`** и **`state/`** в корне репо. Перед коммитом workflow копирует их в **`web/data/`** и **`web/state/`**, потому что сайт на Vercel читает данные только из `web/data` и `web/state`.
3. Результаты (и корневые `data/`, `state/`, и `web/data/`, `web/state/`) коммитятся и **пушатся только в ветку `crawl/daily`**; в `main` ничего не попадает.
4. Из последнего `state/runs/*.json` собирается отчёт (по каждому источнику: total, new, status).
5. Если задан `RESEND_API_KEY`, на **pilikoff@gmail.com** уходит письмо с этим отчётом и ссылкой из `PUBLISH_LINK`.
6. Переход по ссылке открывает `GET /api/publish-to-production?token=...`. При верном `token` (равном `PUBLISH_SECRET`) выполняется **merge crawl/daily → main**. В main попадают в том числе обновлённые `web/data/` и `web/state/`. После пуша Vercel деплоит — на бое появляются новые данные (в т.ч. новые релизы Future Fonts и др.).

## Безопасность

- Ссылку «слить на бой» знайте только вы; не светите её публично.
- `PUBLISH_SECRET` и `PUBLISH_GITHUB_TOKEN` храните только в секретах/переменных, не в коде.
