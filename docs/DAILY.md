# Daily (incremental) parsers

Режим `--daily` предназначен для коротких ежедневных прогонов без полного обхода каталогов. Основные парсеры **не меняются**: подключаются другие режимы краулинга и сужаются параметры через run plan.

## Как устроено

1. **Watermarks** хранятся в `state/daily_watermarks.json`: по каждому источнику `last_run_utc` и `last_date`. Следующий daily-запуск берёт окно дат `[last_date, today]` (при первом запуске — вчера–сегодня).

2. **Run plan** при `daily=True` строит для каждого источника отдельный конфиг:
   - подставляет другой `crawl.mode` там, где есть «лёгкий» режим;
   - задаёт `start_date` / `end_date` и уменьшенные лимиты из watermarks.

3. После успешного прогона источника его watermark обновляется (текущая дата), чтобы следующий run снова ходил только «от последнего раза».

## Поведение по источникам

| Источник         | Обычный режим              | Daily: режим / ограничения |
|------------------|----------------------------|----------------------------|
| **myfonts**      | `myfonts_api` (полный API)  | `myfonts_whats_new`, окно по датам, до 15 страниц |
| **type_today**   | `type_today_api` (полный API) | `type_today_journal`, окно по датам постов |
| **futurefonts**  | `futurefonts_activity`      | Тот же режим; окно по датам, 5 стр. activity, detail_fetch_limit=20, typeface_fetch_limit=50 |
| **fontstand**    | `fontstand_catalog` (полный каталог) | `fontstand_new_releases` — только New Releases (RSS + loadMore) за окно дат, матч по filteredfonts (первые 5 стр. с sort=release-date) |
| **typenetwork**  | `typenetwork_public_families` | Тот же режим; `lookback_days=7`, включён date cutoff |
| **contemporarytype** | `contemporarytype_products` | Тот же режим; `detail_fetch_limit=20` |

## Запуск

```bash
python3 -m src.main --daily
```

Можно ограничить источники:

```bash
python3 -m src.main --daily --sources myfonts,type_today,futurefonts
```

Если daily не срабатывал несколько дней и нужно вручную добрать данные за период — для MyFonts задайте даты (в daily используется режим whats-new):

```bash
python3 -m src.main --daily --sources myfonts --myfonts-start-date 2026-03-01 --myfonts-end-date 2026-03-07
```

Окно дат по умолчанию берётся из watermark (last_date → today); при указании `--myfonts-start-date` и `--myfonts-end-date` в daily используются они.

## Валидация MyFonts daily

Чтобы не считать «новыми» релизы из-за сбоя фильтра по дате, для MyFonts в режиме `--daily` список новых релизов пересчитывается по **диффу с предыдущим снимком**: в `new_releases.json` попадают только те релизы, которых нет в `all_releases.json` последнего предыдущего дня. В логе выводится `raw_new` (до валидации) и `vs_previous_snapshot` (после). Если предыдущего снимка нет, используется сырой результат краулера.

## Файлы

- Конфиг источников: `config/sources.json` (для daily подставляются только override’ы в run plan).
- Логика daily: `src/orchestration/run_plan.py` (`_apply_daily_overrides`), `src/state/daily_watermarks.py`.
- Основные краулеры (`myfonts_api`, `type_today_api`, `futurefonts_activity`, и т.д.) **не изменяются**; для myfonts и type_today в daily просто вызываются уже существующие `myfonts_whats_new` и `type_today_journal`.

## Автозапуск для Vercel (GitHub Actions)

Workflow `.github/workflows/daily-crawl.yml`:

- **Расписание:** каждый день в 06:00 UTC (и ручной **Run workflow**).
- Результаты парсинга пушатся **только в ветку `crawl/daily`** (в `main` не попадают).
- После прогона на **pilikoff@gmail.com** уходит отчёт (количество нового по источникам) и **ссылка «Слить на бой»**. По переходу по ссылке выполняется слияние `crawl/daily` → `main`; Vercel деплоит — на сайте появляются новые данные.

Подробно: [docs/DAILY_VERCEL_REPORT.md](DAILY_VERCEL_REPORT.md) (секреты Resend, PUBLISH_LINK, переменные Vercel).

Чтобы workflow мог пушить в `crawl/daily`: **Settings → Actions → General → Workflow permissions** → **Read and write permissions**.
