import { promises as fs } from "node:fs";
import path from "node:path";

import { ReleasesByWeek, type WeekGroup } from "@/components/releases-by-week";
import type { ReleaseItem } from "@/components/release-card";
import { SourceLinks } from "@/app/source-links";
import { loadSourceMetaMap, sourceFaviconUiUrl, type SourceUiMeta } from "@/lib/source-meta";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type CoverageWeek = {
  week_start: string;
  week_end: string;
  label: string;
};

type CoverageSource = {
  weeks?: CoverageWeek[];
};

type DataCoverage = {
  generated_at?: string;
  sources?: Record<string, CoverageSource>;
};

let resolvedProjectRoot: string | null = null;

async function resolveProjectRoot(): Promise<string> {
  if (resolvedProjectRoot) return resolvedProjectRoot;
  const candidates = [process.cwd(), path.resolve(process.cwd(), "..")];
  for (const candidate of candidates) {
    try {
      const st = await fs.stat(path.join(candidate, "data"));
      if (st.isDirectory()) {
        resolvedProjectRoot = candidate;
        return candidate;
      }
    } catch {
      continue;
    }
  }
  resolvedProjectRoot = process.cwd();
  return resolvedProjectRoot;
}

async function readJsonArray<T>(filePath: string): Promise<T[]> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

async function readDownloadedImageRelative(baseDir: string, releaseId: string): Promise<string | null> {
  const filePath = path.join(baseDir, "assets", releaseId, "downloaded_assets.json");
  try {
    const raw = await fs.readFile(filePath, "utf8");
    const parsed = JSON.parse(raw) as { image?: string };
    return parsed.image || null;
  } catch {
    return null;
  }
}

function toPosixPath(p: string): string {
  return p.replace(/\\/g, "/");
}

async function withLocalImages(baseDir: string, sourceRelPrefix: string, releases: ReleaseItem[]): Promise<ReleaseItem[]> {
  const out = await Promise.all(
    releases.map(async (release) => {
      const releaseId = release.release_id;
      if (!releaseId) return release;

      const imageRel = await readDownloadedImageRelative(baseDir, releaseId);
      if (!imageRel) return release;

      const fullRel = toPosixPath(path.join(sourceRelPrefix, imageRel));
      const localUrl = `/api/assets?p=${encodeURIComponent(fullRel)}`;
      return { ...release, image_url: localUrl };
    })
  );
  return out;
}

async function findLatestPeriodDir(sourceId: string): Promise<string | null> {
  const root = await resolveProjectRoot();
  const periodsDir = path.join(root, "data", sourceId, "periods");

  try {
    const entries = await fs.readdir(periodsDir, { withFileTypes: true });
    const periodDirs = entries
      .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort((a, b) => b.localeCompare(a));

    return periodDirs[0] ?? null;
  } catch {
    return null;
  }
}

async function findLatestDayDir(sourceId: string): Promise<string | null> {
  const root = await resolveProjectRoot();
  const sourceDir = path.join(root, "data", sourceId);

  try {
    const entries = await fs.readdir(sourceDir, { withFileTypes: true });
    const dayDirs = entries
      .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort((a, b) => b.localeCompare(a));

    return dayDirs[0] ?? null;
  } catch {
    return null;
  }
}

async function loadSourceReleases(sourceId: string): Promise<ReleaseItem[]> {
  const root = await resolveProjectRoot();
  const sourceDir = path.join(root, "data", sourceId);
  const latestPeriod = await findLatestPeriodDir(sourceId);
  const latestDay = await findLatestDayDir(sourceId);
  const chunks: ReleaseItem[][] = [];

  if (latestPeriod) {
    const periodBaseDir = path.join(sourceDir, "periods", latestPeriod);
    const periodPath = path.join(periodBaseDir, "all_releases.json");
    const releases = await readJsonArray<ReleaseItem>(periodPath);
    chunks.push(await withLocalImages(periodBaseDir, path.join(sourceId, "periods", latestPeriod), releases));
  }

  if (latestDay) {
    const dayBaseDir = path.join(sourceDir, latestDay);
    const dayPath = path.join(dayBaseDir, "all_releases.json");
    const dayReleases = await readJsonArray<ReleaseItem>(dayPath);
    chunks.push(await withLocalImages(dayBaseDir, path.join(sourceId, latestDay), dayReleases));
  }

  if (chunks.length > 0) {
    return chunks.flat();
  }

  try {
    const entries = await fs.readdir(sourceDir, { withFileTypes: true });
    const dateDirs = entries
      .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort((a, b) => b.localeCompare(a));

    const all = await Promise.all(
      dateDirs.map(async (day) => {
        const dayBaseDir = path.join(sourceDir, day);
        const rows = await readJsonArray<ReleaseItem>(path.join(dayBaseDir, "all_releases.json"));
        return withLocalImages(dayBaseDir, path.join(sourceId, day), rows);
      })
    );

    return all.flat();
  } catch {
    return [];
  }
}

function normalizeDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const datePart = value.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(datePart) ? datePart : null;
}

function inRange(day: string, start: string, end: string): boolean {
  return day >= start && day <= end;
}

function parseIsoDate(value: string): Date | null {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatWeekRangeRu(startIso: string, endIso: string): string {
  const start = parseIsoDate(startIso);
  const end = parseIsoDate(endIso);
  if (!start || !end) return `${startIso} - ${endIso}`;

  const sameYear = start.getFullYear() === end.getFullYear();
  const sameMonth = sameYear && start.getMonth() === end.getMonth();

  const dayMonthFmt = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
  const dayMonthYearFmt = new Intl.DateTimeFormat("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });

  function monthGenitive(date: Date): string {
    const value = dayMonthFmt.format(date).trim();
    const parts = value.split(/\s+/);
    return parts.slice(1).join(" ");
  }

  if (sameMonth) {
    return `${start.getDate()} — ${end.getDate()} ${monthGenitive(start)}`;
  }
  if (sameYear) {
    return `${dayMonthFmt.format(start)} — ${dayMonthFmt.format(end)}`;
  }
  return `${dayMonthYearFmt.format(start)} — ${dayMonthYearFmt.format(end)}`;
}

async function loadCoverageWeeks(): Promise<CoverageWeek[]> {
  const root = await resolveProjectRoot();
  const coveragePath = path.join(root, "state", "data_coverage.json");

  try {
    const raw = await fs.readFile(coveragePath, "utf8");
    const coverage = JSON.parse(raw) as DataCoverage;
    const byKey = new Map<string, CoverageWeek>();

    for (const source of Object.values(coverage.sources ?? {})) {
      for (const week of source.weeks ?? []) {
        const key = `${week.week_start}|${week.week_end}`;
        if (!byKey.has(key)) {
          byKey.set(key, week);
        }
      }
    }

    return Array.from(byKey.values()).sort((a, b) => b.week_start.localeCompare(a.week_start));
  } catch {
    return [];
  }
}

async function loadAllReleasesDeduped(sourceIds: string[], sourceMetaMap: Record<string, SourceUiMeta>): Promise<ReleaseItem[]> {
  const groups = await Promise.all(sourceIds.map((sourceId) => loadSourceReleases(sourceId)));
  const unique = new Map<string, ReleaseItem>();

  for (const release of groups.flat()) {
    const key =
      release.release_id ||
      `${release.source_id}:${release.source_url ?? ""}:${release.name}:${release.release_date ?? ""}`;

    if (!unique.has(key)) {
      const sourceMeta = sourceMetaMap[release.source_id];
      unique.set(key, {
        ...release,
        source_name: release.source_name || sourceMeta?.name || release.source_id,
        source_url: release.source_url || sourceMeta?.baseUrl || null,
        source_favicon_url: sourceFaviconUiUrl(sourceMeta)
      });
    }
  }

  return Array.from(unique.values());
}

function buildWeekGroups(releases: ReleaseItem[], weeks: CoverageWeek[]): WeekGroup[] {
  const buckets = new Map<string, ReleaseItem[]>();

  for (const week of weeks) {
    buckets.set(`${week.week_start}|${week.week_end}`, []);
  }

  for (const release of releases) {
    const day = normalizeDate(release.release_date);
    if (!day) continue;

    const week = weeks.find((item) => inRange(day, item.week_start, item.week_end));
    if (!week) continue;

    const key = `${week.week_start}|${week.week_end}`;
    const arr = buckets.get(key);
    if (arr) arr.push(release);
  }

  return weeks
    .map((week) => {
      const id = `${week.week_start}|${week.week_end}`;
      const weekReleases = (buckets.get(id) ?? []).sort((a, b) => {
        const da = normalizeDate(a.release_date) ?? "";
        const db = normalizeDate(b.release_date) ?? "";
        return db.localeCompare(da);
      });

      return {
        id,
        label: week.label,
        uiLabel: formatWeekRangeRu(week.week_start, week.week_end),
        releaseCount: weekReleases.length,
        releases: weekReleases
      };
    })
    .filter((week) => week.releaseCount > 0);
}

export default async function HomePage() {
  const [sourceMetaMap, coverageWeeks] = await Promise.all([loadSourceMetaMap(), loadCoverageWeeks()]);
  const sourceIds = Object.keys(sourceMetaMap);
  const releases = await loadAllReleasesDeduped(sourceIds, sourceMetaMap);
  const weekGroups = buildWeekGroups(releases, coverageWeeks);

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 lg:px-8">
      <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Font Releases</h1>
        <SourceLinks />
      </header>

      <ReleasesByWeek weekGroups={weekGroups} />
    </main>
  );
}
