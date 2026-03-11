from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from src.state.daily_watermarks import daily_start_end_dates


@dataclass
class RunOptions:
    source_filter: set[str] | None = None
    myfonts_debut_date: str | None = None
    myfonts_start_date: str | None = None
    myfonts_end_date: str | None = None
    myfonts_fresh_run: bool = False
    myfonts_start_page: int | None = None
    history_weeks: int | None = None
    history_end_date: str | None = None
    daily: bool = False
    daily_watermarks: dict[str, dict[str, Any]] | None = None


@dataclass
class RunPlanItem:
    source_id: str
    source_cfg: dict[str, Any]


@dataclass
class RunPlan:
    items: list[RunPlanItem]
    history_start: str | None = None
    history_end: str | None = None
    period_label: str | None = None


def build_run_plan(
    sources: list[dict[str, Any]],
    options: RunOptions,
) -> RunPlan:
    use_daily = options.daily and options.daily_watermarks is not None
    history_start, history_end = _resolve_history_range(options.history_weeks, options.history_end_date)
    period_label = f"{history_start}_{history_end}" if history_start and history_end else None
    if use_daily:
        period_label = None

    items: list[RunPlanItem] = []
    for raw_source_cfg in sources:
        source_id = raw_source_cfg["id"]
        if options.source_filter and source_id not in options.source_filter:
            continue
        if use_daily:
            source_cfg = _apply_daily_overrides(
                raw_source_cfg=raw_source_cfg,
                source_id=source_id,
                watermarks=options.daily_watermarks,
                myfonts_start_date=options.myfonts_start_date,
                myfonts_end_date=options.myfonts_end_date,
            )
        else:
            source_cfg = _apply_source_overrides(
                source_cfg=raw_source_cfg,
                source_id=source_id,
                myfonts_debut_date=options.myfonts_debut_date,
                myfonts_start_date=options.myfonts_start_date,
                myfonts_end_date=options.myfonts_end_date,
                myfonts_fresh_run=options.myfonts_fresh_run,
                myfonts_start_page=options.myfonts_start_page,
                history_start=history_start,
                history_end=history_end,
            )
        items.append(RunPlanItem(source_id=source_id, source_cfg=source_cfg))

    return RunPlan(
        items=items,
        history_start=history_start,
        history_end=history_end,
        period_label=period_label,
    )


def _apply_daily_overrides(
    raw_source_cfg: dict[str, Any],
    source_id: str,
    watermarks: dict[str, dict[str, Any]],
    myfonts_start_date: str | None = None,
    myfonts_end_date: str | None = None,
) -> dict[str, Any]:
    """
    Build source_cfg for a daily (incremental) run. Does not modify main crawlers:
    - Switches to light mode where one exists (myfonts_whats_new, type_today_journal).
    - Окно дат: из watermark (last_date → today). Для MyFonts при --daily можно задать
      даты вручную (--myfonts-start-date / --myfonts-end-date) для backfill при пропущенных прогонах.
    """
    if source_id == "myfonts" and myfonts_start_date and myfonts_end_date:
        start_date = _parse_ymd(myfonts_start_date) or date.today()
        end_date = _parse_ymd(myfonts_end_date) or date.today()
    else:
        # MyFonts без watermark: только "сегодня". Остальные: вчера–сегодня.
        fallback_days = 0 if source_id == "myfonts" else 1
        start_date, end_date = daily_start_end_dates(
            watermarks, source_id, fallback_days_back=fallback_days
        )
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()

    updated = dict(raw_source_cfg)
    crawl = dict(updated.get("crawl") or {})

    if source_id == "myfonts":
        crawl["mode"] = "myfonts_whats_new"
        crawl["start_date"] = start_str
        crawl["end_date"] = end_str
        # max_pages не ограничиваем: остановка по датам (debut < start_date в краулере)
    elif source_id == "type_today":
        crawl["mode"] = "type_today_journal"
        crawl["start_date"] = start_str
        crawl["end_date"] = end_str
    elif source_id == "futurefonts":
        crawl["start_date"] = start_str
        crawl["end_date"] = end_str
        crawl["max_pages_per_type"] = 5
        crawl["detail_fetch_limit"] = 20
        crawl["typeface_fetch_limit"] = 50
        crawl["lookback_days"] = 7
    elif source_id == "typenetwork":
        crawl["start_date"] = start_str
        crawl["end_date"] = end_str
        crawl["disable_date_cutoff"] = False
        crawl["lookback_days"] = 7
    elif source_id == "contemporarytype":
        crawl["detail_fetch_limit"] = 0
    else:
        crawl["start_date"] = start_str
        crawl["end_date"] = end_str

    updated["crawl"] = crawl
    return updated


def _apply_source_overrides(
    source_cfg: dict[str, Any],
    source_id: str,
    myfonts_debut_date: str | None,
    myfonts_start_date: str | None,
    myfonts_end_date: str | None,
    myfonts_fresh_run: bool,
    myfonts_start_page: int | None,
    history_start: str | None,
    history_end: str | None,
) -> dict[str, Any]:
    updated = source_cfg

    if source_id == "myfonts" and (myfonts_debut_date or myfonts_start_date or myfonts_end_date):
        updated = dict(updated)
        updated["crawl"] = dict(updated.get("crawl", {}))
        if myfonts_debut_date:
            updated["crawl"]["start_date"] = myfonts_debut_date
            updated["crawl"]["end_date"] = myfonts_debut_date
            updated["crawl"]["target_debut_date"] = myfonts_debut_date
        if myfonts_start_date:
            updated["crawl"]["start_date"] = myfonts_start_date
        if myfonts_end_date:
            updated["crawl"]["end_date"] = myfonts_end_date

    if source_id == "myfonts" and myfonts_fresh_run:
        updated = dict(updated)
        updated["crawl"] = dict(updated.get("crawl", {}))
        updated["crawl"]["force_fresh_run"] = True

    if source_id == "myfonts" and myfonts_start_page and myfonts_start_page > 1:
        updated = dict(updated)
        updated["crawl"] = dict(updated.get("crawl", {}))
        updated["crawl"]["start_page_override"] = int(myfonts_start_page)

    if history_start and history_end:
        updated = dict(updated)
        updated["crawl"] = dict(updated.get("crawl", {}))
        if source_id == "myfonts":
            updated["crawl"]["start_date"] = history_start
            updated["crawl"]["end_date"] = history_end
        if source_id == "type_today":
            updated["crawl"]["start_date"] = history_start
            updated["crawl"]["end_date"] = history_end
        if source_id == "futurefonts":
            updated["crawl"]["start_date"] = history_start
            updated["crawl"]["end_date"] = history_end
            start_dt = datetime.strptime(history_start, "%Y-%m-%d").date()
            delta_days = (date.today() - start_dt).days + 7
            updated["crawl"]["lookback_days"] = max(
                int(updated["crawl"].get("lookback_days", 30)),
                delta_days,
            )
        if source_id == "typenetwork":
            updated["crawl"]["start_date"] = history_start
            updated["crawl"]["end_date"] = history_end

    return updated


def _resolve_history_range(
    history_weeks: int | None,
    history_end_date: str | None,
) -> tuple[str | None, str | None]:
    if not history_weeks or history_weeks <= 0:
        return None, None
    end_day = _parse_ymd(history_end_date) or date.today()
    start_day = end_day - timedelta(days=history_weeks * 7 - 1)
    return start_day.isoformat(), end_day.isoformat()


def _parse_ymd(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
