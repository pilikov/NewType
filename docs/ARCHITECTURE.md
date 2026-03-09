# Architecture (Current)

Этот документ фиксирует текущую целевую структуру миграции и фактическое состояние проекта после Phase 1.

## Слои

1. `Crawlers`
- Source-specific extraction логика.
- Контракт: `src/crawlers/base.py` (`Crawler` protocol).
- Общие helper'ы для снижения дублирования: `src/crawlers/shared/`.

2. `Orchestration`
- Выбор реализации краулера по `crawl.mode`.
- Текущая реализация registry: `src/orchestration/registry.py`.
- Планирование запуска/override-конфигов: `src/orchestration/run_plan.py`.

3. `Storage`
- Контракт для хранения релизов: `src/storage/base.py` (`StorageAdapter` protocol).
- Текущая реализация JSON: `src/storage/json_adapter.py`.
- Фабрика адаптеров: `src/storage/factory.py`.
- Postgres каркас (еще не включен): `src/storage/postgres_adapter.py`.

4. `State`
- Контракт для runtime state: `src/state/base.py` (`StateAdapter` protocol).
- Текущая реализация JSON: `src/state/json_adapter.py` (`state/seen_ids.json`).
- Фабрика адаптеров: `src/state/factory.py`.
- Postgres каркас (еще не включен): `src/state/postgres_adapter.py`.

5. `Domain`
- Модель релиза: `src/models.py`.
- Run модели (каркас для следующих фаз): `src/domain/run_models.py`.
  - `RunContext`
  - `SourceRunSummary`
  - `RunSummary`

6. `Normalization`
- Нормализация выполняется после crawler extraction и до persistence.
- Registry нормализаторов: `src/normalization/pipeline.py`.
- Правило: crawler сохраняет максимально сырой сигнал источника в `release.raw`,
  а адаптация под проектные поля (например `scripts`) делается в normalizer.
- Для MyFonts: `src/normalization/myfonts.py` (интерпретация `tech_specs_supported_languages`).

## Что уже сделано

- Убран hardcoded `if/elif` выбор краулеров из `main.py`.
- Добавлен `CrawlerRegistry` и default registration map.
- Контракты `Crawler`, `StorageAdapter`, `StateAdapter` введены как протоколы.
- `main.py` использует JSON adapters для release persistence и seen state.
- `main.py` получает adapters через factory (`backend=json` по умолчанию).
- `main.py` записывает run metadata в `state/runs/<run_id>.json`.
- `main.py` строит `RunPlan` и итерируется по `RunPlanItem`.
- `main.py` прогоняет релизы через normalization pipeline перед записью.

## Что пока не сделано

- `main.py` все еще содержит логику assets/coverage и orchestration flow.
