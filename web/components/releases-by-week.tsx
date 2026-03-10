"use client";

import { useEffect, useMemo, useState } from "react";

import { ReleaseCard, type ReleaseItem } from "@/components/release-card";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";

export type WeekGroup = {
  id: string;
  label: string;
  uiLabel: string;
  releaseCount: number;
  releases: ReleaseItem[];
};

type ReleasesByWeekProps = {
  weekGroups: WeekGroup[];
};

type FilterOption = {
  id: string;
  label: string;
  releases: ReleaseItem[];
  releaseCount: number;
  sortValue: number;
};

function parseWeekStartFromId(id: string): Date | null {
  const start = id.split("|")[0];
  if (!/^\d{4}-\d{2}-\d{2}$/.test(start)) return null;
  const dt = new Date(`${start}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? null : dt;
}

function monthLabelEn(year: number, monthIndex: number): string {
  const dt = new Date(Date.UTC(year, monthIndex, 1));
  const month = new Intl.DateTimeFormat("en-US", { month: "short" }).format(dt);
  return `${month} ${String(year).slice(-2)}`;
}

function sortReleasesDesc(items: ReleaseItem[]): ReleaseItem[] {
  return [...items].sort((a, b) => (b.release_date ?? "").localeCompare(a.release_date ?? ""));
}

const filterButtonClass =
  "rounded-[var(--radius)] border-0 min-h-11 px-5 py-2.5 text-base";
const filterButtonInactiveClass = `${filterButtonClass} bg-[#F8F8F8] hover:bg-[#EFEFED]`;

export function ReleasesByWeek({ weekGroups }: ReleasesByWeekProps) {
  const filterOptions = useMemo<FilterOption[]>(() => {
    const nowYear = new Date().getFullYear();

    const byMonth2025 = new Map<string, { year: number; month: number; releases: ReleaseItem[] }>();
    const byYear = new Map<number, ReleaseItem[]>();
    const currentYearWeeks: FilterOption[] = [];

    for (const week of weekGroups) {
      const start = parseWeekStartFromId(week.id);
      if (!start) continue;
      const year = start.getFullYear();
      const month = start.getMonth();

      if (year === nowYear) {
        currentYearWeeks.push({
          id: `week:${week.id}`,
          label: week.uiLabel,
          releases: sortReleasesDesc(week.releases),
          releaseCount: week.releaseCount,
          sortValue: start.getTime()
        });
        continue;
      }

      if (year === 2025) {
        const key = `${year}-${String(month + 1).padStart(2, "0")}`;
        const current = byMonth2025.get(key);
        if (current) {
          current.releases.push(...week.releases);
        } else {
          byMonth2025.set(key, { year, month, releases: [...week.releases] });
        }
        continue;
      }

      const current = byYear.get(year);
      if (current) {
        current.push(...week.releases);
      } else {
        byYear.set(year, [...week.releases]);
      }
    }

    const monthOptions: FilterOption[] = Array.from(byMonth2025.values())
      .map((item) => {
        const releases = sortReleasesDesc(item.releases);
        const sortValue = Date.UTC(item.year, item.month, 1);
        return {
          id: `month:${item.year}-${String(item.month + 1).padStart(2, "0")}`,
          label: monthLabelEn(item.year, item.month),
          releases,
          releaseCount: releases.length,
          sortValue
        };
      })
      .sort((a, b) => b.sortValue - a.sortValue);

    const yearOptions: FilterOption[] = Array.from(byYear.entries())
      .map(([year, releases]) => {
        const sorted = sortReleasesDesc(releases);
        return {
          id: `year:${year}`,
          label: String(year),
          releases: sorted,
          releaseCount: sorted.length,
          sortValue: Date.UTC(year, 0, 1)
        };
      })
      .sort((a, b) => b.sortValue - a.sortValue);

    return [...currentYearWeeks.sort((a, b) => b.sortValue - a.sortValue), ...monthOptions, ...yearOptions];
  }, [weekGroups]);

  const [activeFilterId, setActiveFilterId] = useState<string>(filterOptions[0]?.id ?? "");

  useEffect(() => {
    if (!filterOptions.length) {
      setActiveFilterId("");
      return;
    }
    if (!filterOptions.some((item) => item.id === activeFilterId)) {
      setActiveFilterId(filterOptions[0].id);
    }
  }, [filterOptions, activeFilterId]);

  const activeFilter = useMemo(
    () => filterOptions.find((item) => item.id === activeFilterId) ?? filterOptions[0],
    [activeFilterId, filterOptions]
  );

  const visibleReleases = activeFilter?.releases ?? [];

  if (!filterOptions.length) {
    return (
      <section className="rounded-[var(--radius)] border border-dashed border-slate-300 bg-white/70 p-10 text-center text-base text-slate-600">
        No releases to display.
      </section>
    );
  }

  const sourceStats = (() => {
    const map = new Map<string, { sourceName: string; faviconUrl: string | null; count: number }>();
    for (const release of visibleReleases) {
      const key = release.studio_id || release.source_id;
      const label = release.studio_name || release.source_name;
      const favicon = release.studio_favicon_url || release.source_favicon_url || null;
      const current = map.get(key);
      if (current) {
        current.count += 1;
        continue;
      }
      map.set(key, {
        sourceName: label,
        faviconUrl: favicon,
        count: 1
      });
    }
    return Array.from(map.values()).sort((a, b) => b.count - a.count || a.sourceName.localeCompare(b.sourceName));
  })();

  return (
    <section className="space-y-6">
      <div className="z-20" style={{ position: "sticky", top: 0 }}>
        <div className="overflow-x-auto">
          <ButtonGroup className="min-w-max">
            {filterOptions.map((item) => {
              const isActive = item.id === activeFilter?.id;
              return (
                <Button
                  key={item.id}
                  variant={isActive ? "default" : "secondary"}
                  className={isActive ? `${filterButtonClass} border-0` : filterButtonInactiveClass}
                  onClick={() => setActiveFilterId(item.id)}
                >
                  {item.label}
                </Button>
              );
            })}
          </ButtonGroup>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-base text-slate-600">
        {sourceStats.map((stat) => (
          <span key={stat.sourceName} className="inline-flex items-center gap-1.5">
            {stat.faviconUrl ? (
              <img src={stat.faviconUrl} alt={stat.sourceName} className="h-4 w-4 rounded-sm" loading="lazy" />
            ) : null}
            <span>{stat.count}</span>
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {visibleReleases.map((release) => (
          <ReleaseCard key={release.release_id} release={release} />
        ))}
      </div>
    </section>
  );
}
