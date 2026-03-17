#!/usr/bin/env node
/**
 * Downloads favicons for news sources from config/news_sources.json
 * and saves them to data/_meta/favicons/{source_id}.{ext}
 *
 * Run from repo root: node scripts/download-news-favicons.mjs
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const configPath = path.join(repoRoot, "config", "news_sources.json");
const faviconDir = path.join(repoRoot, "data", "_meta", "favicons");

const EXT_BY_CONTENT_TYPE = {
  "image/png": ".png",
  "image/x-icon": ".ico",
  "image/vnd.microsoft.icon": ".ico",
  "image/svg+xml": ".svg",
  "image/webp": ".webp",
  "image/jpeg": ".jpg",
  "image/jpg": ".jpg",
  "image/gif": ".gif"
};

function extFromUrl(url) {
  const p = new URL(url).pathname.toLowerCase();
  if (p.endsWith(".png")) return ".png";
  if (p.endsWith(".ico")) return ".ico";
  if (p.endsWith(".svg")) return ".svg";
  if (p.endsWith(".webp")) return ".webp";
  if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return ".jpg";
  if (p.endsWith(".gif")) return ".gif";
  return ".ico";
}

async function downloadFavicon(url, sourceId) {
  const res = await fetch(url, {
    headers: { "User-Agent": "TypeParserFavicon/1.0" }
  });
  if (!res.ok) return null;
  const buf = Buffer.from(await res.arrayBuffer());
  if (!buf.length || buf.length > 1024 * 1024) return null;

  const ct = (res.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
  const ext = EXT_BY_CONTENT_TYPE[ct] || extFromUrl(url) || ".ico";

  await mkdir(faviconDir, { recursive: true });
  const outPath = path.join(faviconDir, `${sourceId}${ext}`);
  await writeFile(outPath, buf);
  return `_meta/favicons/${sourceId}${ext}`;
}

async function main() {
  const raw = await readFile(configPath, "utf8");
  const cfg = JSON.parse(raw);
  const sources = (cfg.sources || []).filter((s) => s.enabled !== false);

  let ok = 0;
  let fail = 0;

  for (const src of sources) {
    const url = src.meta?.favicon_url || (src.base_url ? `${src.base_url.replace(/\/$/, "")}/favicon.ico` : null);
    if (!url) {
      console.warn(`[skip] ${src.id}: no favicon URL`);
      fail++;
      continue;
    }
    try {
      const localPath = await downloadFavicon(url, src.id);
      if (localPath) {
        console.log(`[ok] ${src.id} -> ${localPath}`);
        ok++;
      } else {
        console.warn(`[fail] ${src.id}: download failed`);
        fail++;
      }
    } catch (err) {
      console.warn(`[fail] ${src.id}:`, err.message);
      fail++;
    }
  }

  console.log(`Done: ${ok} ok, ${fail} failed`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
