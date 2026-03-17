import { promises as fs } from "node:fs";
import path from "node:path";

type NewsConfigSource = {
  id?: string;
  name?: string;
  enabled?: boolean;
  base_url?: string;
  meta?: { favicon_url?: string };
};

type NewsConfigPayload = {
  sources?: NewsConfigSource[];
};

export type NewsSourceUiMeta = {
  sourceId: string;
  name: string;
  baseUrl: string | null;
  faviconUrl: string | null;
  faviconLocalPath: string | null;
};

const FAVICON_EXTS = [".ico", ".png", ".svg", ".webp", ".jpg", ".jpeg"];

function toPosixPath(p: string): string {
  return p.replace(/\\/g, "/");
}

export function newsSourceFaviconUiUrl(meta: NewsSourceUiMeta | undefined): string | null {
  if (!meta) return null;
  if (process.env.VERCEL === "1") {
    return meta.faviconUrl;
  }
  if (meta.faviconLocalPath) {
    return `/api/assets?p=${encodeURIComponent(toPosixPath(meta.faviconLocalPath))}`;
  }
  return meta.faviconUrl;
}

async function resolveProjectRoot(): Promise<string> {
  const cwd = process.cwd();
  const candidates = [cwd, path.resolve(cwd, "..")];
  for (const candidate of candidates) {
    try {
      const st = await fs.stat(path.join(candidate, "config", "news_sources.json"));
      if (st.isFile()) return candidate;
    } catch {
      continue;
    }
  }
  return cwd;
}

async function dataDirFromRoot(root: string): Promise<string | null> {
  const candidates = [
    path.join(root, "data"),
    path.join(root, "web", "data"),
    path.resolve(root, "..", "data")
  ];
  for (const candidate of candidates) {
    try {
      const st = await fs.stat(candidate);
      if (st.isDirectory()) return candidate;
    } catch {
      continue;
    }
  }
  return null;
}

export async function loadNewsSourceMetaMap(): Promise<Record<string, NewsSourceUiMeta>> {
  const root = await resolveProjectRoot();
  const dataDir = await dataDirFromRoot(root);
  const result: Record<string, NewsSourceUiMeta> = {};

  try {
    const configPath = path.join(root, "config", "news_sources.json");
    const configRaw = await fs.readFile(configPath, "utf8");
    const cfg = JSON.parse(configRaw) as NewsConfigPayload;

    for (const source of cfg.sources ?? []) {
      if (!source.id || source.enabled === false) continue;

      let faviconLocalPath: string | null = null;
      if (dataDir) {
        const faviconBase = path.join(dataDir, "_meta", "favicons", source.id);
        for (const ext of FAVICON_EXTS) {
          const p = faviconBase + ext;
          try {
            await fs.access(p);
            faviconLocalPath = `_meta/favicons/${source.id}${ext}`;
            break;
          } catch {
            continue;
          }
        }
      }

      const faviconUrl = source.meta?.favicon_url || (source.base_url ? `${source.base_url.replace(/\/$/, "")}/favicon.ico` : null);

      result[source.id] = {
        sourceId: source.id,
        name: source.name || source.id,
        baseUrl: source.base_url || null,
        faviconUrl,
        faviconLocalPath
      };
    }
  } catch (err) {
    console.error("[news-source-meta] load error:", err);
  }

  return result;
}
