import { promises as fs } from "node:fs";
import path from "node:path";

import { NextRequest, NextResponse } from "next/server";

const MIME_BY_EXT: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".pdf": "application/pdf"
};

function getMimeType(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase();
  return MIME_BY_EXT[ext] || "application/octet-stream";
}

function isSafeRelativeDataPath(p: string): boolean {
  if (!p || p.includes("\0")) return false;
  const norm = path.posix.normalize(p.replace(/\\/g, "/"));
  if (norm.startsWith("../") || norm === "..") return false;
  return true;
}

async function resolveDataRoot(): Promise<string | null> {
  const candidates = [path.resolve(process.cwd(), "data"), path.resolve(process.cwd(), "..", "data")];
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

export async function GET(request: NextRequest) {
  const relPath = request.nextUrl.searchParams.get("p") || "";
  if (!isSafeRelativeDataPath(relPath)) {
    return NextResponse.json({ error: "invalid path" }, { status: 400 });
  }

  const dataRoot = await resolveDataRoot();
  if (!dataRoot) {
    return NextResponse.json({ error: "data root not found" }, { status: 500 });
  }
  const absPath = path.resolve(dataRoot, relPath);
  if (!absPath.startsWith(dataRoot + path.sep) && absPath !== dataRoot) {
    return NextResponse.json({ error: "forbidden" }, { status: 403 });
  }

  try {
    const buf = await fs.readFile(absPath);
    const contentType = getMimeType(absPath);
    return new NextResponse(buf, {
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=3600"
      }
    });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
}
