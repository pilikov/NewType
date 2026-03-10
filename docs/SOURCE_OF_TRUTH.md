# Source of Truth

Единственный репозиторий — **NewType**. Весь код и данные для UI (в т.ч. Vercel) находятся здесь.

- **Python / краулер:** `src/`, данные в корневых `data/` и `state/` (локально; в git не коммитятся).
- **Web / Vercel:** `web/`. Перед билдом `prebuild` копирует корневые `data/` и `state/` в `web/data` и `web/state`; при деплое без корневых данных (например, Vercel) используются уже закоммиченные `web/data` и `web/state`.
