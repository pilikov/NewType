# Архитектура системы новостей

## Источники (14 штук, config/news_sources.json)

| id | Метод | Особенности |
|---|---|---|
| type_today | API `/api/v1/posts` | JSON, поле `attributes.date`, lookback_days=60 |
| futurefonts | HTML `/blog` + fetch страниц | date_fetch_limit=10, extract_published_at() |
| adobe_fonts | sitemap.xml | дата из URL `/publish/YYYY/MM/DD/`, font_only фильтр |
| typotheque | RSS | lookback_days=1 (мало новостей) |
| fontfabric | RSS | lookback_days=1 |
| monotype | HTML scrape | `time[datetime]`, limit=40 |
| fontstand | HTML `/news` + fetch страниц | date_fetch_limit=10, многие без дат (published_at=null) |
| typenetwork | HTML `/articles` + fetch | date_fetch_limit=10 |
| losttype | HTML `/news` + fetch | date_fetch_limit=10 |
| boldmonday | HTML `/news` + fetch | date_fetch_limit=10 |
| daltonmaag | HTML, дата из URL (YYYY-MM-DD) | |
| emigre | HTML single page + anchors | дата из текста `<p>` |
| commercialtype | HTML + BFS discovery | seed slugs → expand through /news/ links, max_items=25 |
| grillitype | API `/api/v1/blog/posts` + detail API | дата из `meta.date` "DD.Mon YYYY", fetch_dates_for=50 |

## Извлечение дат (src/crawlers/news/)

**date_extract.py** — `extract_published_at(html, url)`:
1. meta: `article:published_time`, `og:published_time`
2. `<time datetime="...">`
3. data-атрибуты: `data-published`, `data-date`
4. CSS: `div.date`, `div.byline`
5. Нормализация: ISO, RFC2822, "DD Mon YYYY", "Month DD, YYYY", "DD.Mon YYYY"

**date_filter.py** — `filter_items_by_date_window(items, start, end, include_undated=True)`:
- Фильтрует по `published_at`
- `include_undated=True` — консервативно: без даты пропускают фильтр

**rss_mixin.py** — `parse_rss_feed(...)`:
- Поддерживает RSS 2.0 и Atom
- Дата из `<pubDate>` или `<updated>`/<published>`
- Без `start_date/end_date` использует `lookback_days` (по умолчанию 1)

## Хранение данных

**Формат (новый, после рефакторинга):**
```
data/news/{source_id}/all_news.json    # gitignored, пишет краулер
web/data/news/{source_id}/all_news.json  # committed, читает Vercel
```

**Формат айтема:**
```json
{
  "news_id": "sha256(source_id+url)[:16]",
  "source_id": "monotype",
  "source_name": "Monotype",
  "title": "...",
  "url": "https://...",
  "published_at": "2026-03-17",  // или null
  "discovered_at": "2026-03-18T08:16:00Z",
  "raw": {}
}
```

**Старый legacy формат (backward compat):**
```
web/data/news/{source_id}/{YYYY-MM-DD}/all_news.json
```
`page.tsx` читает оба: сначала пробует `all_news.json` напрямую, фолбэк — date dirs (до 30 дней).

## src/news_run.py — логика run_news()

```
для каждого источника:
  1. cfg = _apply_news_daily_overrides() если daily=True
     → start_date = watermark.last_date или (today - 7d)
     → end_date = today
     → lookback_days = max(7, окно)
  2. crawler.crawl(session, timeout) → items[]
  3. out_path = data/news/{source_id}/all_news.json
  4. existing = _load_existing_news(out_path)
     если пусто — _load_existing_from_date_dirs() (миграция со старого формата)
  5. для item in items:
       если item.news_id не в existing → добавить (new_count++)
  6. seen_state[source_id] = sorted(existing.keys())
  7. dump_json(out_path, list(existing.values()))
  8. если daily → update_news_source_watermark()
```

**Ключевое:** логика всегда additive — никогда не удаляет старые айтемы.

## CLI команды

```bash
python3 -m src.main --news                          # полный прогон всех источников
python3 -m src.main --news --news-daily             # дейли: только новые за последние 7 дней
python3 -m src.main --news --news-sources monotype,grillitype  # конкретные источники
```

## Web: web/app/news/page.tsx

- `resolveProjectRoot()` ищет `data/news/` в `cwd/data/news` или `cwd/web/data/news`
- `loadAllNews()`: для каждого source dir читает `all_news.json` (новый формат), фолбэк — date dirs
- Сортировка: датированные сначала (новые → старые), без даты — в конце
- `loadNewsSourceMetaMap()` из `config/news_sources.json` — фавиконы и имена источников

## Vercel: next.config.ts

**КРИТИЧНО:** `outputFileTracingIncludes` должен явно указывать файлы для bundling:
```ts
outputFileTracingIncludes: {
  "/*": [
    "./data/**/all_releases.json",
    "./data/news/**/all_news.json",   // ← обязательно для /news страницы
    "./state/data_coverage.json",
    "./config/sources.json",
    "./config/news_sources.json"      // ← обязательно для favicon/имён источников
  ]
}
```
Без этого `fs.readFile()` на Vercel молча падает → страница пустая.
