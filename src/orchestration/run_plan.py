from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


@dataclass
class RunOptions:
    source_filter: set[str] | None = None
    myfonts_debut_date: str | None = None
    myfonts_start_date: str | None = None
    myfonts_end_date: str | None = None
    myfonts_fresh_run: bool = False
    history_weeks: int | None = None
    history_end_date: str | None = None


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
    history_start, history_end = _resolve_history_range(options.history_weeks, options.history_end_date)
    period_label = f"{history_start}_{history_end}" if history_start and history_end else None

    items: list[RunPlanItem] = []
    for raw_source_cfg in sources:
        source_id = raw_source_cfg["id"]
        if options.source_filter and source_id not in options.source_filter:
            continue
        source_cfg = _apply_source_overrides(
            source_cfg=raw_source_cfg,
            source_id=source_id,
            myfonts_debut_date=options.myfonts_debut_date,
            myfonts_start_date=options.myfonts_start_date,
            myfonts_end_date=options.myfonts_end_date,
            myfonts_fresh_run=options.myfonts_fresh_run,
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


def _apply_source_overrides(
    source_cfg: dict[str, Any],
    source_id: str,
    myfonts_debut_date: str | None,
    myfonts_start_date: str | None,
    myfonts_end_date: str | None,
    myfonts_fresh_run: bool,
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
