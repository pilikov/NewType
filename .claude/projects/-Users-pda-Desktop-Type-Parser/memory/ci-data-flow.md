# CI и поток данных

## Ветки

- `main` — production, деплоится на Vercel автоматически
- `crawl/daily` — накопленные данные между publish-ами, force-push каждый день
- `claude/*` — feature ветки для разработки

## daily-crawl.yml — порядок шагов

```
1. Checkout (из main или текущего ref)
2. Setup Python 3.11 + pip install
3. [ФИКС] Restore accumulated data from crawl/daily:
   - git fetch origin crawl/daily
   - git checkout origin/crawl/daily -- web/data/ web/state/ state/
   - cp web/data/news/*/ → data/news/   ← чтобы краулер видел историю новостей
4. python -m src.main --daily           ← релизы шрифтов
5. python -m src.main --news --news-daily ← новости
6. Mirror data/ → web/data/ (merge, без удаления)
   cp -r data/*/ web/data/*/
   rm -rf web/state && cp -r state web/state
7. git add -f data/ state/ web/data/ web/state/
8. git commit + git push --force origin HEAD:crawl/daily
9. Build report + send email (Resend API)
```

## Почему force-push из main теряет данные (и как исправлено)

```
Day 0 (publish): main ← crawl/daily  [полные данные]

Day 1:
  checkout main → только day0 данные
  краулер добавляет day1
  force-push crawl/daily = day0 + day1  ✓

Day 2 (БЕЗ фикса):
  checkout main → только day0 (day1 потеряно!)
  краулер добавляет day2
  force-push crawl/daily = day0 + day2  ✗ day1 ПОТЕРЯНО

Day 2 (С фиксом — шаг 3):
  checkout main
  restore web/data/ из crawl/daily → получаем day0+day1
  cp web/data/news → data/news
  краулер добавляет day2 поверх day0+day1
  force-push crawl/daily = day0 + day1 + day2  ✓
```

## gitignore важные правила

```
/data/    # gitignored — рабочая директория краулера
/state/   # gitignored — watermarks, seen_ids (локальные)
```
Committed (для Vercel):
```
web/data/   # зеркало data/ для Vercel
web/state/  # зеркало state/ для Vercel
```

## Publish flow

1. CI пушит в `crawl/daily`
2. Email с PUBLISH_LINK (secrets.PUBLISH_LINK)
3. По ссылке: workflow мёрджит crawl/daily → main
4. Vercel автоматически деплоит из main

## Состояние watermarks (новости)

`state/news_daily_watermarks.json`:
```json
{
  "source_id": {
    "last_run_utc": "2026-03-17T08:16:00Z",
    "last_date": "2026-03-17"
  }
}
```
Daily override: `start_date = last_date`, `end_date = today`, `lookback_days = max(7, дней)`
Без watermark (первый запуск): `start_date = today - 7d`
