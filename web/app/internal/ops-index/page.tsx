import { promises as fs } from "node:fs";
import path from "node:path";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type StudioRow = {
  foundry_id?: string | null;
  foundry_name?: string | null;
  foundry_url?: string | null;
  release_count?: number;
  favicon_url?: string | null;
  favicon_status?: string | null;
};

type ReleaseRow = {
  name?: string;
  release_date?: string | null;
  release_date_confidence?: string | null;
  release_date_source_type?: string | null;
  release_date_confidence_score?: number | null;
  source_url?: string | null;
  foundry_name?: string | null;
  scripts?: string[];
  date_basis?: string | null;
};

async function resolveProjectRoot(): Promise<string> {
  const candidates = [process.cwd(), path.resolve(process.cwd(), "..")];
  for (const candidate of candidates) {
    try {
      const snapshotRoot = path.join(candidate, "data", "catalog_snapshot");
      const st = await fs.stat(snapshotRoot);
      if (!st.isDirectory()) continue;
      const entries = await fs.readdir(snapshotRoot, { withFileTypes: true });
      let hasReports = false;
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        if (!/^\d{8}T\d{6}Z$/.test(entry.name)) continue;
        const releasesPath = path.join(
          snapshotRoot,
          entry.name,
          "reports",
          "release_date_enrichment",
          "releases_since_2026_with_scripts.json"
        );
        try {
          const reportSt = await fs.stat(releasesPath);
          if (reportSt.isFile()) {
            hasReports = true;
            break;
          }
        } catch {
          continue;
        }
      }
      if (hasReports) return candidate;
    } catch {
      continue;
    }
  }
  return process.cwd();
}

async function readJsonArray<T>(p: string): Promise<T[]> {
  try {
    const raw = await fs.readFile(p, "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as T[]) : [];
  } catch {
    return [];
  }
}

async function findLatestSnapshotRun(root: string): Promise<string | null> {
  const base = path.join(root, "data", "catalog_snapshot");
  try {
    const entries = await fs.readdir(base, { withFileTypes: true });
    const runs = entries
      .filter((e) => e.isDirectory() && /^\d{8}T\d{6}Z$/.test(e.name))
      .map((e) => e.name)
      .sort((a, b) => b.localeCompare(a));
    for (const run of runs) {
      const releasesPath = path.join(
        base,
        run,
        "reports",
        "release_date_enrichment",
        "releases_since_2026_with_scripts.json"
      );
      try {
        const st = await fs.stat(releasesPath);
        if (st.isFile()) return run;
      } catch {
        continue;
      }
    }
    return runs[0] ?? null;
  } catch {
    return null;
  }
}

type BackdoorProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CatalogSnapshotBackdoorPage({ searchParams }: BackdoorProps) {
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const requiredKey = (process.env.INTERNAL_VIEW_KEY || "").trim();
  if (requiredKey) {
    const provided = resolvedSearchParams?.k;
    const providedValue = Array.isArray(provided) ? provided[0] || "" : provided || "";
    if (providedValue !== requiredKey) {
      notFound();
    }
  }

  const root = await resolveProjectRoot();
  const run = await findLatestSnapshotRun(root);
  if (!run) {
    return <main className="mx-auto max-w-5xl p-8">No catalog snapshot data found.</main>;
  }

  const base = path.join(root, "data", "catalog_snapshot", run, "reports", "release_date_enrichment");
  const [studios, releases] = await Promise.all([
    readJsonArray<StudioRow>(path.join(base, "studios_since_2026_with_favicons.json")),
    readJsonArray<ReleaseRow>(path.join(base, "releases_since_2026_with_scripts.json"))
  ]);

  const topReleases = releases
    .slice()
    .sort((a, b) => String(b.release_date || "").localeCompare(String(a.release_date || "")))
    .slice(0, 200);

  const okFavicon = studios.filter((s) => s.favicon_status === "ok").length;
  const verifiedReleases = releases.filter((r) => {
    const confidence = String(r.release_date_confidence || "").toLowerCase();
    const sourceType = String(r.release_date_source_type || "").toLowerCase();
    if (!r.release_date) return false;
    if (sourceType === "existing" && confidence === "low") return false;
    return true;
  }).length;

  function displayDate(release: ReleaseRow): string {
    const confidence = String(release.release_date_confidence || "").toLowerCase();
    const sourceType = String(release.release_date_source_type || "").toLowerCase();
    if (!release.release_date) return "—";
    if (sourceType === "existing" && confidence === "low") return "—";
    return release.release_date;
  }

  return (
    <main className="mx-auto max-w-7xl p-6 space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">Ops Data View</h1>
        <p className="text-sm text-slate-600">Run: {run}</p>
        <p className="text-sm text-slate-600">
          Studios: {studios.length} · Releases since 2026: {releases.length} · Verified dates: {verifiedReleases} · Favicon coverage:{" "}
          {okFavicon}/{studios.length}
        </p>
      </header>

      <section className="space-y-3">
        <h2 className="text-xl font-medium">Studios</h2>
        <div className="overflow-x-auto rounded border">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="p-2">Icon</th>
                <th className="p-2">Studio</th>
                <th className="p-2">Releases</th>
                <th className="p-2">URL</th>
              </tr>
            </thead>
            <tbody>
              {studios.map((studio) => (
                <tr key={studio.foundry_id || studio.foundry_name} className="border-t">
                  <td className="p-2">
                    {studio.favicon_url ? (
                      <img src={studio.favicon_url} alt={studio.foundry_name || "studio"} className="h-4 w-4" />
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="p-2">{studio.foundry_name || studio.foundry_id || "—"}</td>
                  <td className="p-2">{studio.release_count ?? 0}</td>
                  <td className="p-2">
                    {studio.foundry_url ? (
                      <a className="text-blue-600 hover:underline" href={studio.foundry_url} target="_blank" rel="noreferrer">
                        {studio.foundry_url}
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-medium">Releases (latest 200)</h2>
        <div className="overflow-x-auto rounded border">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="p-2">Date</th>
                <th className="p-2">Release</th>
                <th className="p-2">Studio</th>
                <th className="p-2">Scripts</th>
                <th className="p-2">Confidence</th>
                <th className="p-2">Date Source</th>
                <th className="p-2">URL</th>
              </tr>
            </thead>
            <tbody>
              {topReleases.map((r, idx) => (
                <tr key={`${r.name}-${idx}`} className="border-t">
                  <td className="p-2">{displayDate(r)}</td>
                  <td className="p-2">{r.name || "—"}</td>
                  <td className="p-2">{r.foundry_name || "—"}</td>
                  <td className="p-2">{Array.isArray(r.scripts) && r.scripts.length ? r.scripts.join(", ") : "—"}</td>
                  <td className="p-2">
                    {r.release_date_confidence || "—"}
                    {typeof r.release_date_confidence_score === "number" ? ` (${r.release_date_confidence_score.toFixed(2)})` : ""}
                  </td>
                  <td className="p-2">
                    {r.release_date_source_type || "—"}
                    {r.date_basis ? ` · ${r.date_basis}` : ""}
                  </td>
                  <td className="p-2">
                    {r.source_url ? (
                      <a className="text-blue-600 hover:underline" href={r.source_url} target="_blank" rel="noreferrer">
                        {r.source_url}
                      </a>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
