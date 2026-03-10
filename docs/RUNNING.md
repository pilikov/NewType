# Running Guide

## Backend

Из корня проекта:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m src.main
```

## Полезные режимы запуска

Только выбранные источники:

```bash
python3 -m src.main --sources myfonts,type_today
```

Точечный фильтр MyFonts по дате дебюта:

```bash
python3 -m src.main --sources myfonts --myfonts-debut-date 2026-03-06
```

Диапазон по MyFonts debut:

```bash
python3 -m src.main --sources myfonts --myfonts-start-date 2026-03-01 --myfonts-end-date 2026-03-07
```

MyFonts long-run по умолчанию автоматически продолжает совместимый предыдущий crawl из checkpoint
`state/myfonts_crawl_checkpoint.json`. Чтобы принудительно начать с нуля:

```bash
python3 -m src.main --sources myfonts --myfonts-start-date 2026-01-01 --myfonts-fresh-run
```

Бэкфилл последних N недель:

```bash
python3 -m src.main --history-weeks 10
```

Ежедневный (инкрементальный) прогон — лёгкие парсеры, окно дат по watermark:

```bash
python3 -m src.main --daily
```

См. [docs/DAILY.md](DAILY.md): какие источники в daily используют другой режим (whats-new, journal) и как хранятся watermarks.

## Где смотреть результат

- Релизы: `data/<source>/<date>/all_releases.json`
- Новые релизы: `data/<source>/<date>/new_releases.json`
- Периодный бэкфилл: `data/<source>/periods/<start>_<end>/...`
- State: `state/seen_ids.json`
- Daily watermarks: `state/daily_watermarks.json`
- MyFonts resume checkpoint: `state/myfonts_crawl_checkpoint.json`
- Coverage для UI: `state/data_coverage.json`
- Run metadata: `state/runs/<run_id>.json`

## Frontend (Next.js)

```bash
cd web
npm install
npm run dev
```

Открыть URL из консоли Next (`http://localhost:3000` или другой свободный порт).

## Быстрая проверка после изменений

```bash
bash scripts/smoke_baseline.sh
```

## Короткие команды через Makefile

```bash
make smoke
make run
make web
make mirror-check
make mirror-check-strict
```
