import { cp, mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(webRoot, "..");

const sourceDataDir = path.join(repoRoot, "data");
const sourceCoverageFile = path.join(repoRoot, "state", "data_coverage.json");
const sourceConfigFile = path.join(repoRoot, "config", "sources.json");
const newsConfigFile = path.join(repoRoot, "config", "news_sources.json");
const targetDataDir = path.join(webRoot, "data");
const targetStateDir = path.join(webRoot, "state");
const targetCoverageFile = path.join(targetStateDir, "data_coverage.json");
const targetConfigDir = path.join(webRoot, "config");
const targetConfigFile = path.join(targetConfigDir, "sources.json");

async function exists(p) {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

async function removeDirRecursive(dirPath) {
  try {
    await rm(dirPath, { recursive: true, force: true, maxRetries: 3 });
  } catch (err) {
    if (err.code !== "ENOENT") throw err;
  }
}

async function sync() {
  const isVercel = process.env.VERCEL === "1";
  if (!isVercel) {
    try {
      const { spawn } = await import("node:child_process");
      const downloadScript = path.join(repoRoot, "scripts", "download-news-favicons.mjs");
      if (await exists(downloadScript)) {
        await new Promise((resolve) => {
          const child = spawn("node", [downloadScript], { cwd: repoRoot, stdio: "inherit" });
          child.on("close", () => resolve());
        });
      }
    } catch (err) {
      console.warn("News favicon download skipped:", err.message);
    }
  }
  if (isVercel) {
    // On Vercel, use committed web/data only. Build cache may contain stale ../data
    // which would overwrite correct web/data from git.
    console.log("Vercel build: keeping committed web/data (no sync from repo root).");
  } else if (await exists(sourceDataDir)) {
    await removeDirRecursive(targetDataDir);
    await mkdir(targetDataDir, { recursive: true });
    await cp(sourceDataDir, targetDataDir, { recursive: true });
    console.log("Synced data/ from repo root to web/data.");
  } else {
    console.log("Source data/ not found in repo root. Keeping existing web/data as-is.");
  }

  if (!isVercel) {
    await mkdir(targetStateDir, { recursive: true });
    if (await exists(sourceCoverageFile)) {
      await cp(sourceCoverageFile, targetCoverageFile);
      console.log("Synced state/data_coverage.json from repo root.");
    } else if (!(await exists(targetCoverageFile))) {
      await writeFile(targetCoverageFile, JSON.stringify({ generated_at: null, sources: {} }), "utf8");
      console.log("Root coverage file missing. Wrote empty fallback in web/state.");
    } else {
      console.log("Root coverage file missing. Keeping existing web/state/data_coverage.json.");
    }

    await mkdir(targetConfigDir, { recursive: true });
    if (await exists(sourceConfigFile)) {
      await cp(sourceConfigFile, targetConfigFile);
      console.log("Synced config/sources.json from repo root.");
    } else if (await exists(targetConfigFile)) {
      console.log("Root config/sources.json missing. Keeping existing web/config/sources.json.");
    } else {
      console.log("Root config/sources.json missing and no local fallback in web/config.");
    }
    const targetNewsConfigFile = path.join(targetConfigDir, "news_sources.json");
    if (await exists(newsConfigFile)) {
      await cp(newsConfigFile, targetNewsConfigFile);
      console.log("Synced config/news_sources.json from repo root.");
    }
  }

  console.log("Synced runtime data for Next.js build.");
}

sync().catch((error) => {
  console.error("Failed to sync runtime data:", error);
  process.exit(1);
});
