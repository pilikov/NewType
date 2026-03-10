import { promises as fs } from "node:fs";
import path from "node:path";

import { ReleasesByWeek, type WeekGroup } from "@/components/releases-by-week";
import type { ReleaseItem } from "@/components/release-card";
import { SourceLinks } from "@/app/source-links";
import { loadSourceMetaMap, sourceFaviconUiUrl, type SourceUiMeta } from "@/lib/source-meta";

export const dynamic = "force-dynamic";
export const revalidate = 0;
const USE_LOCAL_ASSET_FILES = process.env.VERCEL !== "1";
const USE_REMOTE_IMAGE_PROXY = process.env.VERCEL !== "1";

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

function asString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function normalizeReleaseItem(input: ReleaseItem, sourceMetaMap: Record<string, SourceUiMeta>): ReleaseItem {
  const sourceId = asString(input.source_id) || "unknown";
  const sourceMeta = sourceMetaMap[sourceId];
  const sourceName = asString(input.source_name) || sourceMeta?.name || sourceId;
  const sourceUrl = asString(input.source_url) || sourceMeta?.baseUrl || null;
  const releaseName = asString(input.name) || "Untitled";
  const releaseDate = asString(input.release_date) || null;
  const authors = asStringArray(input.authors);
  const scripts = asStringArray(input.scripts);
  const imageUrl = asString(input.image_url) || null;
  const releaseId =
    asString(input.release_id) || `${sourceId}:${sourceUrl ?? ""}:${releaseName}:${releaseDate ?? ""}`;

  return {
    ...input,
    release_id: releaseId,
    source_id: sourceId,
    source_name: sourceName,
    source_url: sourceUrl,
    name: releaseName,
    release_date: releaseDate,
    authors,
    scripts,
    image_url: imageUrl,
    source_favicon_url: sourceFaviconUiUrl(sourceMeta)
  };
}

let resolvedProjectRoot: string | null = null;

async function hasAnyReleaseFiles(candidate: string): Promise<boolean> {
  const dataDir = path.join(candidate, "data");
  try {
    const sourceDirs = await fs.readdir(dataDir, { withFileTypes: true });
    for (const source of sourceDirs) {
      if (!source.isDirectory() || source.name.startsWith(".")) continue;
      const sourcePath = path.join(dataDir, source.name);
      try {
        const files = await fs.readdir(sourcePath, { withFileTypes: true });
        for (const entry of files) {
          if (!entry.isDirectory()) continue;
          const maybe = path.join(sourcePath, entry.name, "all_releases.json");
          try {
            const st = await fs.stat(maybe);
            if (st.isFile()) return true;
          } catch {
            continue;
          }
        }
      } catch {
        continue;
      }
    }
  } catch {
    return false;
  }
  return false;
}

async function resolveProjectRoot(): Promise<string> {
  if (resolvedProjectRoot) return resolvedProjectRoot;
  const candidates = [process.cwd(), path.resolve(process.cwd(), "..")];
  for (const candidate of candidates) {
    try {
      const st = await fs.stat(path.join(candidate, "data"));
      if (st.isDirectory() && (await hasAnyReleaseFiles(candidate))) {
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

function toCachedImageUrl(imageUrl: string | null | undefined): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith("/api/assets?p=") || imageUrl.startsWith("/api/assets?u=")) return imageUrl;
  if (imageUrl.startsWith("http://") || imageUrl.startsWith("https://")) {
    if (!USE_REMOTE_IMAGE_PROXY) return imageUrl;
    return `/api/assets?u=${encodeURIComponent(imageUrl)}`;
  }
  return imageUrl;
}

async function withLocalImages(baseDir: string, sourceRelPrefix: string, releases: ReleaseItem[]): Promise<ReleaseItem[]> {
  if (!USE_LOCAL_ASSET_FILES) {
    return releases.map((release) => ({ ...release, image_url: toCachedImageUrl(release.image_url) }));
  }

  const out = await Promise.all(
    releases.map(async (release) => {
      const releaseId = release.release_id;
      if (!releaseId) {
        return { ...release, image_url: toCachedImageUrl(release.image_url) };
      }

      const imageRel = await readDownloadedImageRelative(baseDir, releaseId);
      if (!imageRel) {
        return { ...release, image_url: toCachedImageUrl(release.image_url) };
      }

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
      .sort((a, b) => {
        const [aStart = "", aEnd = ""] = a.split("_");
        const [bStart = "", bEnd = ""] = b.split("_");
        if (aEnd !== bEnd) return bEnd.localeCompare(aEnd);
        if (aStart !== bStart) return aStart.localeCompare(bStart);
        return b.localeCompare(a);
      });

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

  if (latestDay) {
    const dayBaseDir = path.join(sourceDir, latestDay);
    const dayPath = path.join(dayBaseDir, "all_releases.json");
    const dayReleases = await readJsonArray<ReleaseItem>(dayPath);
    chunks.push(await withLocalImages(dayBaseDir, path.join(sourceId, latestDay), dayReleases));
  }

  if (latestPeriod) {
    const periodBaseDir = path.join(sourceDir, "periods", latestPeriod);
    const periodPath = path.join(periodBaseDir, "all_releases.json");
    const releases = await readJsonArray<ReleaseItem>(periodPath);
    chunks.push(await withLocalImages(periodBaseDir, path.join(sourceId, "periods", latestPeriod), releases));
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

function releaseWeekDate(release: ReleaseItem): string | null {
  if (release.source_id === "myfonts") {
    const raw = release.raw as { myfonts_debut_date?: string | null } | undefined;
    const debutDay = normalizeDate(raw?.myfonts_debut_date ?? null) ?? normalizeDate(release.release_date ?? null);
    return debutDay;
  }
  return normalizeDate(release.release_date);
}

function inRange(day: string, start: string, end: string): boolean {
  return day >= start && day <= end;
}

function parseIsoDate(value: string): Date | null {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatWeekRangeEn(startIso: string, endIso: string): string {
  const start = parseIsoDate(startIso);
  const end = parseIsoDate(endIso);
  if (!start || !end) return `${startIso} - ${endIso}`;

  const sameYear = start.getFullYear() === end.getFullYear();
  const sameMonth = sameYear && start.getMonth() === end.getMonth();

  const dayMonthFmt = new Intl.DateTimeFormat("en-US", { day: "numeric", month: "long" });
  const dayMonthYearFmt = new Intl.DateTimeFormat("en-US", {
    day: "numeric",
    month: "long",
    year: "numeric"
  });

  if (sameMonth) {
    const month = new Intl.DateTimeFormat("en-US", { month: "long" }).format(start);
    return `${start.getDate()} — ${end.getDate()} ${month}`;
  }
  if (sameYear) {
    return `${dayMonthFmt.format(start)} — ${dayMonthFmt.format(end)}`;
  }
  return `${dayMonthYearFmt.format(start)} — ${dayMonthYearFmt.format(end)}`;
}

function toIsoDay(date: Date): string {
  const y = date.getUTCFullYear();
  const m = String(date.getUTCMonth() + 1).padStart(2, "0");
  const d = String(date.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function startOfIsoWeek(dayIso: string): string | null {
  const dt = parseIsoDate(dayIso);
  if (!dt) return null;
  const utc = new Date(Date.UTC(dt.getFullYear(), dt.getMonth(), dt.getDate()));
  const dow = utc.getUTCDay();
  const delta = (dow + 6) % 7;
  utc.setUTCDate(utc.getUTCDate() - delta);
  return toIsoDay(utc);
}

function endOfIsoWeek(weekStartIso: string): string | null {
  const dt = parseIsoDate(weekStartIso);
  if (!dt) return null;
  const utc = new Date(Date.UTC(dt.getFullYear(), dt.getMonth(), dt.getDate()));
  utc.setUTCDate(utc.getUTCDate() + 6);
  return toIsoDay(utc);
}

function buildWeeksFromReleases(releases: ReleaseItem[]): CoverageWeek[] {
  const uniq = new Map<string, CoverageWeek>();
  for (const release of releases) {
    const day = releaseWeekDate(release);
    if (!day) continue;
    const weekStart = startOfIsoWeek(day);
    if (!weekStart) continue;
    if (uniq.has(weekStart)) continue;
    const weekEnd = endOfIsoWeek(weekStart);
    if (!weekEnd) continue;
    uniq.set(weekStart, {
      week_start: weekStart,
      week_end: weekEnd,
      label: `${weekStart}_${weekEnd}`
    });
  }
  return Array.from(uniq.values()).sort((a, b) => b.week_start.localeCompare(a.week_start));
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
    const normalized = normalizeReleaseItem(release, sourceMetaMap);
    const key = normalized.release_id;

    if (!unique.has(key)) {
      unique.set(key, normalized);
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
    const day = releaseWeekDate(release);
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
        const da = releaseWeekDate(a) ?? "";
        const db = releaseWeekDate(b) ?? "";
        return db.localeCompare(da);
      });

      return {
        id,
        label: week.label,
        uiLabel: formatWeekRangeEn(week.week_start, week.week_end),
        releaseCount: weekReleases.length,
        releases: weekReleases
      };
    })
    .filter((week) => week.releaseCount > 0);
}

export default async function HomePage() {
  const [sourceMetaMap, coverageWeeks] = await Promise.all([loadSourceMetaMap(), loadCoverageWeeks()]);
  const sourceIds = Object.keys(sourceMetaMap).filter((id) => id !== "catalog_snapshot");
  const releases = await loadAllReleasesDeduped(sourceIds, sourceMetaMap);
  const effectiveWeeks = coverageWeeks.length ? coverageWeeks : buildWeeksFromReleases(releases);
  const weekGroups = buildWeekGroups(releases, effectiveWeeks);

  return (
    <main className="mx-auto w-full max-w-7xl">
      <header className="mb-8 w-full pt-0">
        {/* Логотип на всю ширину рабочей области (main), без отступа сверху */}
        <div className="flex w-full justify-center">
          <img
            src="/Logo.svg"
            alt="Logo"
            className="block h-auto w-full max-w-none"
            width={994}
            height={119}
            decoding="async"
          />
        </div>
        {/* Иконки источников по центру под логотипом */}
        <div className="mt-4 flex w-full justify-center px-4 sm:px-6 lg:px-8">
          <SourceLinks />
        </div>
      </header>

      <div className="px-4 pb-10 pt-0 sm:px-6 lg:px-8">
        <ReleasesByWeek weekGroups={weekGroups} />
      </div>
    </main>
  );
}
