"use client";

import { useMemo, useState } from "react";

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

export function ReleasesByWeek({ weekGroups }: ReleasesByWeekProps) {
  const [activeWeekId, setActiveWeekId] = useState<string>(weekGroups[0]?.id ?? "");

  const activeWeek = useMemo(
    () => weekGroups.find((week) => week.id === activeWeekId) ?? weekGroups[0],
    [activeWeekId, weekGroups]
  );

  if (!weekGroups.length) {
    return (
      <section className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-10 text-center text-slate-600">
        Нет релизов для отображения.
      </section>
    );
  }

  function formatReleaseCount(value: number): string {
    const mod10 = value % 10;
    const mod100 = value % 100;
    if (mod10 === 1 && mod100 !== 11) return `${value} релиз`;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${value} релиза`;
    return `${value} релизов`;
  }

  return (
    <section className="space-y-6">
      <div className="z-20" style={{ position: "sticky", top: 0 }}>
        <div className="overflow-x-auto">
          <ButtonGroup className="min-w-max">
            {weekGroups.map((week) => {
              const isActive = week.id === activeWeek?.id;
              return (
                <Button
                  key={week.id}
                  variant={isActive ? "default" : "secondary"}
                  className={isActive ? "rounded-md border-0" : "rounded-md border-0 bg-[#F8F8F8] hover:bg-[#EFEFED]"}
                  onClick={() => setActiveWeekId(week.id)}
                >
                  {week.uiLabel}
                </Button>
              );
            })}
          </ButtonGroup>
        </div>
      </div>

      <div className="text-sm text-slate-600">{formatReleaseCount(activeWeek?.releaseCount ?? 0)}</div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-3">
        {activeWeek?.releases.map((release) => <ReleaseCard key={release.release_id} release={release} />)}
      </div>
    </section>
  );
}
