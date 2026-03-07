import { promises as fs } from "node:fs";
import path from "node:path";

type CoverageSourceMeta = {
  name?: string | null;
  base_url?: string | null;
  favicon_url?: string | null;
  favicon_local_path?: string | null;
};

type DataCoveragePayload = {
  sources?: Record<string, { meta?: CoverageSourceMeta }>;
};

type ConfigSource = {
  id?: string;
  name?: string;
  enabled?: boolean;
  base_url?: string;
  meta?: {
    favicon_url?: string;
  };
};

type ConfigPayload = {
  sources?: ConfigSource[];
};

export type SourceUiMeta = {
  sourceId: string;
  name: string;
  baseUrl: string | null;
  faviconUrl: string | null;
  faviconLocalPath: string | null;
};

function toPosixPath(p: string): string {
  return p.replace(/\\/g, "/");
}

export function sourceFaviconUiUrl(meta: SourceUiMeta | undefined): string | null {
  if (!meta) return null;
  if (meta.faviconLocalPath) {
    return `/api/assets?p=${encodeURIComponent(toPosixPath(meta.faviconLocalPath))}`;
  }
  return meta.faviconUrl;
}

async function resolveProjectRoot(): Promise<string> {
  const candidates = [process.cwd(), path.resolve(process.cwd(), "..")];
  for (const candidate of candidates) {
    try {
      const st = await fs.stat(path.join(candidate, "config", "sources.json"));
      if (st.isFile()) return candidate;
    } catch {
      continue;
    }
  }
  return process.cwd();
}

export async function loadSourceMetaMap(): Promise<Record<string, SourceUiMeta>> {
  const root = await resolveProjectRoot();
  const result: Record<string, SourceUiMeta> = {};

  try {
    const configRaw = await fs.readFile(path.join(root, "config", "sources.json"), "utf8");
    const cfg = JSON.parse(configRaw) as ConfigPayload;
    for (const source of cfg.sources ?? []) {
      if (!source.id || source.enabled === false) continue;
      result[source.id] = {
        sourceId: source.id,
        name: source.name || source.id,
        baseUrl: source.base_url || null,
        faviconUrl: source.meta?.favicon_url || null,
        faviconLocalPath: null
      };
    }
  } catch {
    // no-op
  }

  try {
    const coverageRaw = await fs.readFile(path.join(root, "state", "data_coverage.json"), "utf8");
    const coverage = JSON.parse(coverageRaw) as DataCoveragePayload;
    for (const [sourceId, payload] of Object.entries(coverage.sources ?? {})) {
      const meta = payload.meta;
      if (!meta) continue;
      const current = result[sourceId] ?? {
        sourceId,
        name: sourceId,
        baseUrl: null,
        faviconUrl: null,
        faviconLocalPath: null
      };
      result[sourceId] = {
        sourceId,
        name: meta.name || current.name,
        baseUrl: meta.base_url || current.baseUrl,
        faviconUrl: meta.favicon_url || current.faviconUrl,
        faviconLocalPath: meta.favicon_local_path || current.faviconLocalPath
      };
    }
  } catch {
    // no-op
  }

  return result;
}
