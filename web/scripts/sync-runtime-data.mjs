import { cp, mkdir, rm } from "node:fs/promises";
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

async function sync() {
  await rm(targetDataDir, { recursive: true, force: true });
  await mkdir(targetDataDir, { recursive: true });
  await cp(sourceDataDir, targetDataDir, { recursive: true });

  await mkdir(targetStateDir, { recursive: true });
  await cp(sourceCoverageFile, targetCoverageFile);

  console.log("Synced runtime data for Next.js build.");
}

sync().catch((error) => {
  console.error("Failed to sync runtime data:", error);
  process.exit(1);
});
