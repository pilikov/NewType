# Migration JSON to Postgres/Neon

Текущий статус: runtime работает на JSON adapters, Postgres adapters пока каркасные (`NotImplementedError`).

## Цель

Перейти на Postgres/Neon без big bang rewrite и без потери текущего поведения.

## Принципы

1. Сначала parity, потом switch.
2. Один источник истины на этапе switch (без смешанных чтений).
3. Любой этап должен быть откатываем.

## Этапы миграции

## Phase A: Реализация Postgres adapters

Реализовать:

- `src/storage/postgres_adapter.py`
- `src/state/postgres_adapter.py`

Нужно покрыть те же контракты, что у JSON adapters:

- persist/load/write/merge releases
- load/save seen ids

## Phase B: Схема БД

Минимальные таблицы:

1. `releases`
- `release_id` PK
- `source_id`
- `source_url`
- payload полей `FontRelease`
- timestamps

2. `seen_ids` (или эквивалент курсора)
- `source_id`
- `release_id`

3. `runs`
- `run_id`
- started/finished
- summary payload (jsonb)

## Phase C: Dual-write (опционально, но рекомендовано)

Временно писать в JSON + Postgres в одном run.

Цель:

- сравнить counts и выборки по релизам
- убедиться в idempotency upsert-логики

## Phase D: Switch read/write

1. Переключить factory backend на `postgres`.
2. Оставить JSON как fallback/rollback path.
3. Наблюдать несколько прогонов.

## Phase E: Cleanup

После стабилизации:

- убрать dual-write
- оставить экспорт в JSON как отдельную утилиту (если нужен для web/runtime)

## Rollback

Rollback всегда через factory configuration:

- вернуть backend на `json`
- не трогать crawler/orchestration код

Это и есть ключевая ценность текущего adapter слоя.
