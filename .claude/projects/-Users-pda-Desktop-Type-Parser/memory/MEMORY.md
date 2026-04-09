# Type Parser — память проекта

## Ключевые файлы

- Конфиг источников: `config/sources.json` (релизы), `config/news_sources.json` (новости)
- Точка входа: `src/main.py` (релизы + `--news` флаг вызывает `src/news_run.py`)
- Модели: `src/models.py` — `FontRelease`, `FontNewsItem`
- Web: `web/` — Next.js 15, Vercel Root Directory = `web/`
- Данные (gitignored): `data/`, `state/`
- Данные для Vercel (committed): `web/data/`, `web/state/`

→ Подробнее: [news-architecture.md](news-architecture.md), [ci-data-flow.md](ci-data-flow.md)

## Критичные баги, которые уже были и исправлены

1. **Vercel file tracing** — `next.config.ts` → `outputFileTracingIncludes` должен явно перечислять все файлы, которые нужны на Vercel. Без этого `fs.readFile()` молча падает, страница возвращает `[]`.
2. **CI теряет данные между публикациями** — CI стартует из `main`, поэтому без специального шага теряет всё накопленное в `crawl/daily` между publish-ами. Фикс: шаг «Restore accumulated data from crawl/daily» в `daily-crawl.yml`.
3. **News: per-date директории vs накапливающий файл** — старая схема писала `data/news/{source}/{date}/all_news.json`, page.tsx читал только 7 последних дат. Теперь: один `data/news/{source}/all_news.json` на источник, всегда additive merge.
