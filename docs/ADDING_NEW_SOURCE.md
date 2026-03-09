# Adding New Source

Порядок добавления нового источника без поломки текущей системы.

## 1. Добавить источник в конфиг

Файл: `config/sources.json`

Минимально нужно:

- `id`
- `name`
- `base_url`
- `crawl.mode`
- `enabled`

`crawl.mode` должен совпасть с регистрацией в crawler registry.

## 2. Реализовать crawler

Создай файл в `src/crawlers/<your_mode>.py`.

Требуемый контракт:

- класс с `source_config`
- метод `crawl(self, session, timeout=20) -> list[FontRelease]`
- опционально `set_release_callback(...)` для incremental flush

Ориентир: существующие crawler-файлы в `src/crawlers/`.

## 3. Зарегистрировать mode

Файл: `src/orchestration/registry.py`

Добавь:

1. import нового crawler
2. `registry.register("<crawl.mode>", <YourCrawlerClass>)`

## 4. Использовать shared helpers (если подходят)

Перед копипастом проверь `src/crawlers/shared/`:

- `dates.py`
- `text.py`
- `next_data.py`
- `html.py`

## 5. Локальная проверка

1. Smoke:

```bash
bash scripts/smoke_baseline.sh
```

2. Точечный прогон источника:

```bash
python3 -m src.main --sources <source_id>
```

3. Проверить, что появились данные:

- `data/<source_id>/<date>/all_releases.json`
- `data/<source_id>/<date>/new_releases.json`

## 6. Критерии готовности

- `source_id` уникален в `config/sources.json`
- crawler не ломает run при частичной ошибке (ошибки ловятся на уровне source-run)
- релизы сериализуются через `FontRelease`
- smoke проходит
