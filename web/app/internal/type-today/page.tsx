import { promises as fs } from "node:fs";
import path from "node:path";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type ReleaseRow = {
  release_id?: string;
  name?: string;
  source_url?: string | null;
  release_date?: string | null;
  authors?: string[];
  styles?: string[];
  scripts?: string[];
  raw?: Record<string, unknown>;
};

type MissingReport = {
  generated_at?: string;
  total_releases?: number;
  missing_counts?: Record<string, number>;
};

type NormalizationReport = {
  generated_at?: string;
  normalization_findings?: Record<string, { count?: number }>;
  recommendations?: string[];
};

type MonitorReport = {
  generated_at?: string;
  baseline_count?: number;
  new_release_count?: number;
  removed_release_count?: number;
  changed_release_count?: number;
  monitoring_plan?: string[];
};

async function resolveProjectRoot(): Promise<string> {
  const candidates = [process.cwd(), path.resolve(process.cwd(), "..")];
  for (const candidate of candidates) {
    try {
      const st = await fs.stat(path.join(candidate, "data", "type_today"));
      if (st.isDirectory()) return candidate;
    } catch {
      continue;
    }
  }
  return process.cwd();
}

async function readJson<T>(filePath: string, fallback: T): Promise<T> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

async function findLatestTypeTodayDir(root: string): Promise<{ abs: string; rel: string } | null> {
  const sourceDir = path.join(root, "data", "type_today");
  try {
    const entries = await fs.readdir(sourceDir, { withFileTypes: true });
    const dayDirs = entries
      .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort((a, b) => b.localeCompare(a));
    if (dayDirs[0]) {
      return {
        abs: path.join(sourceDir, dayDirs[0]),
        rel: path.posix.join("type_today", dayDirs[0]),
      };
    }
  } catch {
    // fallthrough
  }

  try {
    const periodsDir = path.join(sourceDir, "periods");
    const entries = await fs.readdir(periodsDir, { withFileTypes: true });
    const periodDirs = entries
      .filter((entry) => entry.isDirectory() && /^\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}$/.test(entry.name))
      .map((entry) => entry.name)
      .sort((a, b) => b.localeCompare(a));
    if (periodDirs[0]) {
      return {
        abs: path.join(periodsDir, periodDirs[0]),
        rel: path.posix.join("type_today", "periods", periodDirs[0]),
      };
    }
  } catch {
    // no-op
  }
  return null;
}

function asArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

export default async function TypeTodayOpsPage() {
  const root = await resolveProjectRoot();
  const latest = await findLatestTypeTodayDir(root);
  if (!latest) {
    return <main className="mx-auto max-w-6xl p-8">No type.today data found.</main>;
  }

  const releases = await readJson<ReleaseRow[]>(path.join(latest.abs, "all_releases.json"), []);
  const missingReport = await readJson<MissingReport>(
    path.join(latest.abs, "reports", "type_today_missing_fields.json"),
    {}
  );
  const normalizationReport = await readJson<NormalizationReport>(
    path.join(latest.abs, "reports", "type_today_normalization_plan.json"),
    {}
  );
  const monitorReport = await readJson<MonitorReport>(
    path.join(latest.abs, "reports", "type_today_monitor_report.json"),
    {}
  );

  const sample = releases.slice(0, 5);
  const rawHref = `/api/assets?p=${encodeURIComponent(path.posix.join(latest.rel, "reports", "type_today_raw_releases.json"))}`;

  return (
    <main className="mx-auto max-w-7xl p-6 space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">type.today API Ops</h1>
        <p className="text-sm text-slate-600">Dataset: {latest.rel}</p>
        <p className="text-sm text-slate-600">Total releases: {releases.length}</p>
        <a className="text-blue-600 hover:underline text-sm" href={rawHref} target="_blank" rel="noreferrer">
          Open raw releases JSON
        </a>
      </header>

      <section className="space-y-2">
        <h2 className="text-xl font-medium">Missing Fields</h2>
        <p className="text-sm text-slate-600">Generated: {missingReport.generated_at || "—"}</p>
        <div className="overflow-x-auto rounded border">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="p-2">Field Check</th>
                <th className="p-2">Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(missingReport.missing_counts || {}).map(([key, value]) => (
                <tr key={key} className="border-t">
                  <td className="p-2">{key}</td>
                  <td className="p-2">{value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-medium">Normalization Findings</h2>
        <p className="text-sm text-slate-600">Generated: {normalizationReport.generated_at || "—"}</p>
        <div className="overflow-x-auto rounded border">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left">
              <tr>
                <th className="p-2">Finding</th>
                <th className="p-2">Count</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(normalizationReport.normalization_findings || {}).map(([key, value]) => (
                <tr key={key} className="border-t">
                  <td className="p-2">{key}</td>
                  <td className="p-2">{value?.count ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="list-disc ml-5 text-sm text-slate-700">
          {asArray(normalizationReport.recommendations).map((rec) => (
            <li key={rec}>{rec}</li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-medium">Monitor</h2>
        <p className="text-sm text-slate-600">Generated: {monitorReport.generated_at || "—"}</p>
        <div className="grid gap-2 md:grid-cols-4 text-sm">
          <div className="rounded border p-3">Baseline: {monitorReport.baseline_count ?? 0}</div>
          <div className="rounded border p-3">New: {monitorReport.new_release_count ?? 0}</div>
          <div className="rounded border p-3">Removed: {monitorReport.removed_release_count ?? 0}</div>
          <div className="rounded border p-3">Changed: {monitorReport.changed_release_count ?? 0}</div>
        </div>
        <ul className="list-disc ml-5 text-sm text-slate-700">
          {asArray(monitorReport.monitoring_plan).map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <h2 className="text-xl font-medium">Sample Raw Rows</h2>
        <div className="space-y-3">
          {sample.map((row) => (
            <details key={row.release_id || row.name} className="rounded border p-3">
              <summary className="cursor-pointer text-sm">
                {row.name || "Untitled"} · {(row.authors || []).join(", ") || "no authors"} · {(row.styles || []).length} styles
              </summary>
              <pre className="mt-3 overflow-auto text-xs bg-slate-50 p-3 rounded">
                {JSON.stringify(
                  {
                    release_id: row.release_id,
                    name: row.name,
                    source_url: row.source_url,
                    release_date: row.release_date,
                    authors: row.authors,
                    scripts: row.scripts,
                    styles_count: (row.styles || []).length,
                    raw: row.raw,
                  },
                  null,
                  2
                )}
              </pre>
            </details>
          ))}
        </div>
      </section>
    </main>
  );
}
