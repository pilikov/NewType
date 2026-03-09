# Storage Layer

Текущий статус: JSON является основным backend.

## Контракты

- `StorageAdapter`: [base.py](/Users/pda/Desktop/Type Parser/src/storage/base.py)
- `StateAdapter`: [base.py](/Users/pda/Desktop/Type Parser/src/state/base.py)

## Текущий runtime backend

- `JsonStorageAdapter`: [json_adapter.py](/Users/pda/Desktop/Type Parser/src/storage/json_adapter.py)
- `JsonStateAdapter`: [json_adapter.py](/Users/pda/Desktop/Type Parser/src/state/json_adapter.py)

`main.py` создает адаптеры через factory:

- [factory.py](/Users/pda/Desktop/Type Parser/src/storage/factory.py)
- [factory.py](/Users/pda/Desktop/Type Parser/src/state/factory.py)

И использует `backend="json"` как default.

## Postgres/Neon readiness (подготовлено, но не включено)

Каркасные адаптеры:

- [postgres_adapter.py](/Users/pda/Desktop/Type Parser/src/storage/postgres_adapter.py)
- [postgres_adapter.py](/Users/pda/Desktop/Type Parser/src/state/postgres_adapter.py)

Они сейчас intentionally бросают `NotImplementedError`.

## Почему так

Это позволяет:

1. Сохранить текущую стабильность JSON-пайплайна.
2. Разрабатывать Postgres реализацию отдельно.
3. Переключение делать контролируемо после тестов (и позже dual-write).
