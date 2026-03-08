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
