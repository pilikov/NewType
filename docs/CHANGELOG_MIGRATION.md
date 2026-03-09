# Migration Changelog

## Phase 0

Статус: completed

Сделано:
- Добавлен baseline smoke: `scripts/smoke_baseline.sh`
- Добавлен baseline guide: `docs/BASELINE_CHECKS.md`

Результат:
- Есть повторяемая проверка "не сломали текущее поведение" до и после этапов.

## Phase 1

Статус: completed

Сделано:
- Добавлен crawler контракт: `src/crawlers/base.py`
- Добавлен registry: `src/orchestration/registry.py`
- `main.py` переведен на registry для выбора краулера
- Добавлены каркасные контракты:
  - `src/storage/base.py`
  - `src/state/base.py`
  - `src/domain/run_models.py`
- Добавлен архитектурный документ: `docs/ARCHITECTURE.md`

Что не менялось по поведению:
- Формат данных в `data/` и `state/`
- CLI аргументы и flow запуска
- Логика работы source-specific краулеров

## Phase 2

Статус: completed

Сделано:
- Добавлен JSON storage adapter: `src/storage/json_adapter.py`
- Добавлен JSON state adapter: `src/state/json_adapter.py`
- Расширен storage protocol: `src/storage/base.py`
- `main.py` переведен на adapters для:
  - `seen_ids` загрузки/сохранения
  - чтения/мержа/записи `all_releases.json` и `new_releases.json`

Что не менялось по поведению:
- Формат и пути JSON-артефактов в `data/` и `state/`
- Инкрементальная логика `release_id`/`seen_ids`
- CLI и source-specific crawl поведение

## Phase 3

Статус: completed

Сделано:
- Введено run metadata в runtime:
  - `run_id` и `RunContext`
  - per-source `SourceRunSummary` со статусом/счетчиками/длительностью
  - итоговый `RunSummary`
- Добавлена запись structured run summary:
  - `state/runs/<run_id>.json`

Формат файла:
- `context`: параметры запуска (`run_id`, `started_at`, `source_filter`, `timeout_seconds`)
- `summary`: `started_at`/`finished_at` и массив source-результатов

Что не менялось по поведению:
- Основной поток краулинга, сохранение релизов и `seen_ids`
- CLI аргументы
- Формат данных в `data/*` и `state/data_coverage.json`

## Phase 4

Статус: completed

Сделано:
- Добавлен `RunPlan` слой:
  - `RunOptions`
  - `RunPlanItem`
  - `RunPlan`
  - builder + override logic в `src/orchestration/run_plan.py`
- `main.py` переведен с inline source selection/overrides на `build_run_plan(...)`

Что не менялось по поведению:
- Порядок обработки источников (по конфигу)
- Логика `--sources`, `--myfonts-*`, `--history-*`
- Результаты сохранения в `data/*`, `state/*`

## Phase 5

Статус: completed

Сделано:
- Добавлены shared crawler helpers:
  - `src/crawlers/shared/text.py`
  - `src/crawlers/shared/dates.py`
  - `src/crawlers/shared/next_data.py`
  - `src/crawlers/shared/html.py`
- Краулеры переведены на shared-утилиты (без изменения алгоритмов):
  - `type_today_journal`
  - `type_today_next`
  - `html_list`
  - `myfonts_whats_new`
  - `myfonts_api`
  - `futurefonts_activity`
  - частично `typenetwork_public_families` (YMD parse)

Что не менялось по поведению:
- Source-specific extraction flow и поля `FontRelease`
- CLI и orchestration flow
- Формат сохранения данных в `data/*` и `state/*`

## Phase 6

Статус: completed

Сделано:
- Добавлены Postgres skeleton adapters (без включения):
  - `src/storage/postgres_adapter.py`
  - `src/state/postgres_adapter.py`
- Добавлены adapter factories:
  - `src/storage/factory.py`
  - `src/state/factory.py`
- `main.py` переведен на factory wiring c backend=`json` по умолчанию.

Что не менялось по поведению:
- Runtime продолжает работать через JSON adapters
- Формат и расположение файлов в `data/*` и `state/*`
- CLI и crawl flow

## Phase 7 (Docs/Guide)

Статус: completed

Сделано:
- Добавлены эксплуатационные гайды:
  - `docs/RUNNING.md`
  - `docs/ADDING_NEW_SOURCE.md`
  - `docs/MIGRATION_JSON_TO_POSTGRES.md`
- Обновлен `README.md` с индексом документации.

Что не менялось по поведению:
- Runtime/CLI/структура данных

## Phase 8 (Mirror Drift Guard)

Статус: completed

Сделано:
- Добавлен drift-check script:
  - `scripts/check_src_mirror.sh`
  - режимы: report-only и `--strict`
- Добавлена документация:
  - `docs/SOURCE_OF_TRUTH.md`
  - обновлен `docs/RUNNING.md`
  - обновлен `README.md`

Что не менялось по поведению:
- Runtime/CLI/формат данных
- Логика краулеров
