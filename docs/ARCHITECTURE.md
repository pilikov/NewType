# Architecture (Current)

Этот документ фиксирует текущую целевую структуру миграции и фактическое состояние проекта после Phase 1.

## Слои

1. `Crawlers`
- Source-specific extraction логика.
- Контракт: `src/crawlers/base.py` (`Crawler` protocol).

2. `Orchestration`
- Выбор реализации краулера по `crawl.mode`.
- Текущая реализация registry: `src/orchestration/registry.py`.

3. `Storage`
- Контракт для хранения релизов: `src/storage/base.py` (`StorageAdapter` protocol).
- Текущая реализация JSON: `src/storage/json_adapter.py`.

4. `State`
- Контракт для runtime state: `src/state/base.py` (`StateAdapter` protocol).
- Текущая реализация JSON: `src/state/json_adapter.py` (`state/seen_ids.json`).

5. `Domain`
- Модель релиза: `src/models.py`.
- Run модели (каркас для следующих фаз): `src/domain/run_models.py`.
  - `RunContext`
  - `SourceRunSummary`
  - `RunSummary`

## Что уже сделано

- Убран hardcoded `if/elif` выбор краулеров из `main.py`.
- Добавлен `CrawlerRegistry` и default registration map.
- Контракты `Crawler`, `StorageAdapter`, `StateAdapter` введены как протоколы.
- `main.py` использует JSON adapters для release persistence и seen state.
- `main.py` записывает run metadata в `state/runs/<run_id>.json`.

## Что пока не сделано

- `main.py` все еще содержит логику assets/coverage и orchestration flow.
