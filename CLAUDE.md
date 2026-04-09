# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

**Type Parser** (internal name: NewType) is a daily font release tracker. A Python pipeline crawls 6 typography sources (MyFonts, Type.Today, Future Fonts, Type Network, Contemporary Type, Fontstand), stores releases as JSON, and displays them via a Next.js web UI deployed to Vercel.

## Commands

### Python backend

```bash
# Setup (once)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run all crawlers
make run  # or: .venv/bin/python -m src.main

# Run specific sources
python3 -m src.main --sources myfonts,type_today

# Daily incremental mode (used by CI)
python3 -m src.main --daily

# Backfill N weeks of history
python3 -m src.main --history-weeks 10

# MyFonts with date filter
python3 -m src.main --sources myfonts --myfonts-start-date 2026-03-01 --myfonts-end-date 2026-03-07

# Smoke/sanity checks
make smoke  # or: bash scripts/smoke_baseline.sh
```

### Web frontend

```bash
cd web && npm install
npm run dev       # Dev server at localhost:3000
npm run build     # Production build (runs prebuild sync first)
npm run lint      # Next.js lint
```

## Architecture

### Data Flow

```
Sources → Crawlers → Normalizers → JSON Storage (data/<source>/<date>/)
                                 → Asset Downloads (images, WOFF, PDFs)
                                 → State Updates (seen_ids, watermarks)
                                 → Web Sync (web/data/, web/state/)
                                 → Git push → Vercel deploy
```

### Python Layers (`src/`)

| Layer | Location | Purpose |
|---|---|---|
| Domain model | `src/models.py` | `FontRelease` dataclass; stable `release_id` = SHA256(source_id + url) |
| Crawlers | `src/crawlers/` | Source-specific extraction, `Crawler` protocol in `base.py` |
| Shared helpers | `src/crawlers/shared/` | Date parsing, HTML extraction, Next.js state parsing |
| Orchestration | `src/orchestration/` | `CrawlerRegistry` (mode→class), `RunPlan` (date windows) |
| Storage | `src/storage/` | `StorageAdapter` protocol; JSON impl active, Postgres scaffolded |
| State | `src/state/` | `StateAdapter` protocol; JSON impl tracking seen IDs + watermarks |
| Normalization | `src/normalization/` | Pipeline after extraction, before persistence |
| Enrichment | `src/enrichment/` | Post-crawl metadata supplements (journal dates, tech specs) |
| Reports | `src/reports/` | Ops/quality reports for Type.Today |
| Entry point | `src/main.py` | CLI args, source config loading, full pipeline orchestration |

### Key State Files

- `state/seen_ids.json` — all-time seen release IDs per source (prevents duplicates)
- `state/daily_watermarks.json` — last run date per source (bounds daily crawl window)
- `state/myfonts_crawl_checkpoint.json` — resume point for interrupted MyFonts crawls
- `state/data_coverage.json` — week-based coverage summary consumed by the web UI
- `state/runs/<run_id>.json` — per-run metadata and summaries

### Output Data Layout

```
data/<source_id>/<YYYY-MM-DD>/
    all_releases.json       # Complete catalog for that source/date
    new_releases.json       # Only releases unseen before this run
    assets/<release_id>/    # Downloaded images, WOFF, PDFs
data/<source_id>/periods/<start>_<end>/  # Backfill ranges
```

### Web Frontend (`web/`)

- Next.js 15 + React 19 + Tailwind CSS + shadcn components
- Main gallery: `web/app/page.tsx` — loads all releases, groups by week
- Internal ops: `web/app/internal/` — Type.Today quality dashboard
- Asset proxy: `web/app/api/assets/route.ts` — proxies locally downloaded files
- **Data source**: `web/data/` and `web/state/` (mirrored from root before build via `scripts/sync-runtime-data.mjs`)

### Source Configuration

All crawl sources are defined in `config/sources.json`. Each entry has `id`, `name`, `base_url`, `crawl.mode`, and `assets` settings. The `crawl.mode` string maps to a class in `src/orchestration/registry.py`.

### CI/CD

`.github/workflows/daily-crawl.yml` runs at 06:00 UTC:
1. Runs `python -m src.main --daily`
2. Mirrors data to `web/data/` and `web/state/`
3. Force-pushes to `crawl/daily` branch
4. Sends email report via Resend API

**Required secrets:** `RESEND_API_KEY`, `PUBLISH_LINK`

## Adding a New Source

1. Add entry to `config/sources.json` with unique `id` and `crawl.mode`
2. Create `src/crawlers/<mode>.py` implementing the `Crawler` protocol (`crawl(self, session, timeout)`)
3. Register in `src/orchestration/registry.py`
4. Test: `python3 -m src.main --sources <id>` → verify `data/<id>/<date>/all_releases.json`
5. Run `make smoke`

See `docs/ADDING_NEW_SOURCE.md` for full checklist.

## Important Conventions

- Crawlers preserve raw source data in `release.raw`; normalization (field mapping) happens in `src/normalization/`
- `IncrementalSourceWriter` flushes to disk every 25 releases — do not buffer large release lists in memory
- `release_id` is deterministic (SHA256 of source+URL) — same release has same ID across runs
- Daily mode uses lighter crawlers (`whats_new`, `journal` variants) and restricts date window via watermarks
- `web/data/` and `web/state/` are **derived** — never edit them directly; they come from root `data/` and `state/`
