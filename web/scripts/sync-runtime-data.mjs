import { cp, mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const webRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(webRoot, "..");

const sourceDataDir = path.join(repoRoot, "data");
const sourceCoverageFile = path.join(repoRoot, "state", "data_coverage.json");
const targetDataDir = path.join(webRoot, "data");
const targetStateDir = path.join(webRoot, "state");
const targetCoverageFile = path.join(targetStateDir, "data_coverage.json");

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
  await cleanDir(targetDataDir);
  if (await exists(sourceDataDir)) {
    await cp(sourceDataDir, targetDataDir, { recursive: true });
  }

  await mkdir(targetStateDir, { recursive: true });
  if (await exists(sourceCoverageFile)) {
    await cp(sourceCoverageFile, targetCoverageFile);
  } else {
    await writeFile(targetCoverageFile, JSON.stringify({ generated_at: null, sources: {} }), "utf8");
  }

  console.log("Synced runtime data for Next.js build.");
}

sync().catch((error) => {
  console.error("Failed to sync runtime data:", error);
  process.exit(1);
});
