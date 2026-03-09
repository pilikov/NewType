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

async function cleanDir(dirPath) {
  await mkdir(dirPath, { recursive: true });
  const entries = await readdir(dirPath, { withFileTypes: true });
  for (const entry of entries) {
    const abs = path.join(dirPath, entry.name);
    let attempts = 0;
    while (attempts < 3) {
      try {
        await rm(abs, { recursive: true, force: true });
        break;
      } catch (error) {
        attempts += 1;
        if (attempts >= 3) throw error;
      }
    }
  }
}

async function sync() {
  if (await exists(sourceDataDir)) {
    await cleanDir(targetDataDir);
    await cp(sourceDataDir, targetDataDir, { recursive: true });
    console.log("Synced data/ from repo root to web/data.");
  } else {
    console.log("Source data/ not found in repo root. Keeping existing web/data as-is.");
  }

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

  console.log("Synced runtime data for Next.js build.");
}

sync().catch((error) => {
  console.error("Failed to sync runtime data:", error);
  process.exit(1);
});
