# Source of Truth and Mirror Drift

Сейчас в репозитории есть два Python-контура:

1. `src/` — основной контур разработки (source of truth)
2. `typerelease-sync/src/` — зеркальный/исторический контур

Полного объединения пока нет, поэтому введена явная проверка дрейфа.

## Проверка дрейфа

Report-only (не валит процесс):

```bash
bash scripts/check_src_mirror.sh
```

Strict mode (exit 1 при расхождении):

```bash
bash scripts/check_src_mirror.sh --strict
```

## Практика до финального объединения

1. Любые архитектурные изменения делать в `src/`.
2. Регулярно смотреть drift-отчет.
3. До переключения CI на strict режим использовать report-only.

## Следующий шаг

Отдельным этапом: решить судьбу `typerelease-sync/src/` (удаление дубликата или перевод на общий пакет).
