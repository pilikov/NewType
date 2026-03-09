# TypeNetwork Crawler Logic

Документ описывает текущую рабочую логику источника `typenetwork` в проекте.

## 1. Где находится код

- Краулер: `src/crawlers/typenetwork_public_families.py`
- Подключение crawl-mode: `src/main.py` (`typenetwork_public_families`)
- Конфиг источника: `config/sources.json` (`id: "typenetwork"`)

## 2. Базовый источник данных

Основные данные берутся из публичного API Type Network:

- `GET https://api.typenetwork.com/api/1/public/families/`

Используемые поля семейства:

- `id`
- `name`
- `slug`
- `catalog_url`
- `released`
- `uploaded`
- `foundry` (список id foundry)
- `supported_scripts` (список id письменностей)
- `supported_languages`
- `variable`

Дополнительно для имен foundry:

- `GET https://api.typenetwork.com/api/1/foundries/`

## 3. Пайплайн по шагам

1. Загрузка конфига `crawl` для источника `typenetwork`.
2. Подтягивание справочника `foundry_id -> foundry_name` из `foundries_endpoint`.
3. Пагинация по `public/families` (`next`-ссылки API).
4. Применение датовых ограничений (если не отключены).
5. Нормализация карточки релиза:
   - `name` = `family.name`
   - `source_url` = `catalog_url` (или fallback `/foundry/{ee_subdomain}/fonts/{slug}`)
   - `authors` = имена foundry по id
   - `scripts` = маппинг `supported_scripts` по `script_id_map`
   - `release_date` = `released` (fallback `uploaded`)
6. Опциональный image enrichment (см. раздел 5).
7. Запись `FontRelease` + сырых данных в `raw`.
8. Инкрементальная запись `all_releases.json` / `new_releases.json` через callback writer.

## 4. Формирование `scripts`

Источник даёт только ID в `supported_scripts`.  
Маппинг задаётся в `config/sources.json` в `crawl.script_id_map`.

Текущий рабочий маппинг:

- `160` -> `Arabic`
- `200` -> `Greek`
- `215` -> `Latin`
- `220` -> `Cyrillic`
- `315` -> `Devanagari`
- `345` -> `Kannada`
- `907` -> `Indic`

Если id не найден в словаре, в `scripts` пишется `Unknown (<id>)`.

## 5. Логика image enrichment (TN-specific)

Цель: найти промо-картинку семейства на сайте соответствующей foundry.

Алгоритм:

1. Берём `foundry_name` (первый автор из `authors`).
2. Переходим на страницу foundry в TypeNetwork:
   - `https://typenetwork.com/type-foundries/{name-with-dashes}`
   - fallback со slugify.
3. Находим внешний сайт foundry среди ссылок страницы:
   - исключаем соцсети и ссылки внутри `typenetwork.com`.
4. На сайте foundry ищем страницы семейства:
   - сначала по ссылкам с homepage (по токенам семейства),
   - если пусто, fallback на `sitemap.xml`.
5. На найденных страницах выбираем лучшую картинку:
   - приоритет `og:image`, затем `twitter:image`, затем `<img src>`,
   - скоринг по совпадению токенов семейства в URL/alt.
6. Если найдено, сохраняем в `release.image_url` и пишем метаданные в
   `raw.image_enrichment`:
   - `status: "ok"`,
   - `foundry_name`,
   - `foundry_site_url`,
   - `image_page_url`.

Статусы неуспеха:

- `no_foundry_name`
- `foundry_site_not_found`
- `promo_not_found`

## 6. Ограничители и режим full scan

Поддерживаемые настройки в `crawl`:

- `page_size`
- `max_pages`
- `ordering`
- `lookback_days`
- `start_date`
- `end_date`
- `disable_date_cutoff`
- `enable_image_enrichment`
- `image_enrichment_limit`
- `image_site_page_limit`

Семантика "без лимита":

- `max_pages <= 0` -> без ограничения страниц
- `disable_date_cutoff: true` -> без нижней даты
- `image_enrichment_limit <= 0` -> image enrichment для всех семейств
- `image_site_page_limit <= 0` -> без лимита страниц на сайте foundry

## 7. Ассеты (скачивание картинок локально)

Общий шаг пайплайна в `src/main.py` (`maybe_download_assets`):

- для TN используется `assets.download_image: true`
- `download_for_all_releases: true` позволяет скачивать не только `new_releases`
- `max_downloads_per_run <= 0` -> без лимита скачиваний за запуск

Структура:

- `data/typenetwork/<date>/assets/<release_id>/...`
- `downloaded_assets.json` рядом в папке релиза

## 8. Что пишется в output

За запуск:

- `data/typenetwork/<YYYY-MM-DD>/all_releases.json`
- `data/typenetwork/<YYYY-MM-DD>/new_releases.json`

Каждый релиз содержит:

- `scripts` (уже нормализованные названия)
- `raw.supported_scripts` (исходные id из API)
- `raw.image_enrichment` (статус и технические детали image enrichment)

## 9. Нюанс с count в API (важно)

В `public/families` наблюдается расхождение:

- `count = 2252` (строк в API-выдаче)
- уникальных `family_id = 2247`

Причина: 5 дублирующихся строк в API (одинаковые `id` повторяются 2 раза).
Поэтому критерий "полного сбора" для нас: покрыты все уникальные `family_id`.

Известные дубли:

- `3607` (`P22 Sneaky`)
- `3608` (`P22 Sniplash`)
- `3609` (`P22 Snowflakes`)
- `3610` (`P22 Sparrow`)
- `4699` (`Clobberin' Time`)

## 10. Практика запуска

Только TN:

```bash
./.venv/bin/python -m src.main --sources typenetwork --timeout 45
```

Проверка прогресса:

```bash
jq 'length' data/typenetwork/<YYYY-MM-DD>/all_releases.json
curl -s 'https://api.typenetwork.com/api/1/public/families/?page_size=1&ordering=-released' | jq '.count'
```

Интерпретация прогресса:

- если `all_releases` == `2247`, полный уникальный охват достигнут;
- если сравнивать с `count=2252`, последние "5" обычно являются API-дублями.
