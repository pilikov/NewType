# Type Release Crawler (Stage 1)

Ежедневный краулер новых релизов шрифтов по источникам с унифицированным JSON-форматом.

## Источники (пока)
- `myfonts`
- `type_today`
- `futurefonts`
- `typenetwork`

Настраиваются в `config/sources.json`.

## Что сохраняется
Для каждого релиза:
- Название (`name`)
- Начертания (`styles`)
- Авторы (`authors`)
- Письменности (`scripts`)
- Дата релиза (`release_date`)
- Ссылка на картинку (`image_url`)
- Ссылка на WOFF (`woff_url`)
- Ссылка на specimen PDF (`specimen_pdf_url`)

Также записываются `source_id`, `source_url`, `discovered_at`, `release_id`, `raw`.

## Запуск
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m src.main
```

## UI (shadcn + Next.js)
Интерфейс находится в папке `web/`.

Запуск:
```bash
cd web
npm install
npm run dev
```

Открыть в браузере:
`http://localhost:3000`

### Deploy на Vercel (минимум действий)
1. В корне проекта запустить:
```bash
./deploy-vercel.sh
```
2. В интерактивном мастере Vercel:
- выбрать текущий scope/account;
- подтвердить деплой в `production`.

Скрипт автоматически:
- запускает деплой из `web/`;
- перед билдом синхронизирует `data/` и `state/data_coverage.json` в `web/`, чтобы UI корректно работал на Vercel.

Только выбранные источники:
```bash
python3 -m src.main --sources myfonts,type_today
```

Фильтр MyFonts по `MyFonts debut` (дата в `YYYY-MM-DD`):
```bash
python3 -m src.main --sources myfonts --myfonts-debut-date 2026-03-06
```

Диапазон дат для MyFonts debut:
```bash
python3 -m src.main --sources myfonts --myfonts-start-date 2026-03-01 --myfonts-end-date 2026-03-07
```

Бэкфилл за последние N недель (для источников с датовыми фильтрами):
```bash
python3 -m src.main --history-weeks 10
```

## Структура данных
- `data/<source>/<YYYY-MM-DD>/all_releases.json`
- `data/<source>/<YYYY-MM-DD>/new_releases.json`
- `data/<source>/periods/<YYYY-MM-DD>_<YYYY-MM-DD>/...` (результат бэкфилла по диапазону)
- `data/<source>/<YYYY-MM-DD>/assets/<release_id>/...` (если удалось скачать)
- `state/seen_ids.json` (инкрементальный state между запусками)
- `state/data_coverage.json` (покрытие дат и список доступных недель для UI)

## Примечания
- Реализованы source-specific адаптеры:
  - `myfonts_api` (через `products.json`)
  - `type_today_journal` (через `ru/journal` посты `Новый шрифт: ...`)
  - `futurefonts_activity` (через `activity` API: `new releases` + `new versions`)
  - `typenetwork_public_families` (через `api/1/public/families`, поле `released`)
- `release_id` стабилен по `source_id + source_url` (или имени, если URL нет), чтобы обновления даты/метаданных не считались новым релизом.
- `woff`/`specimen_pdf` скачиваются только если в источнике реально присутствует прямая ссылка.
