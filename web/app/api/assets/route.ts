import { promises as fs } from "node:fs";
import crypto from "node:crypto";
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

function isAllowedRemoteUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

function extensionFromRemote(url: string, contentType: string): string {
  const ct = (contentType || "").toLowerCase();
  if (ct.includes("image/png")) return ".png";
  if (ct.includes("image/webp")) return ".webp";
  if (ct.includes("image/svg")) return ".svg";
  if (ct.includes("image/gif")) return ".gif";
  if (ct.includes("image/jpeg") || ct.includes("image/jpg")) return ".jpg";
  if (ct.includes("image/x-icon") || ct.includes("image/vnd.microsoft.icon")) return ".ico";
  const ext = path.extname(new URL(url).pathname).toLowerCase();
  if (ext) return ext;
  return ".img";
}

async function readOrCacheRemoteImage(dataRoot: string, remoteUrl: string): Promise<{ buf: Uint8Array; contentType: string } | null> {
  const cacheDir = path.join(dataRoot, "_meta", "image-cache");
  await fs.mkdir(cacheDir, { recursive: true });

  const key = crypto.createHash("sha256").update(remoteUrl).digest("hex");

  try {
    const files = await fs.readdir(cacheDir);
    const existed = files.find((name) => name.startsWith(`${key}.`));
    if (existed) {
      const abs = path.join(cacheDir, existed);
      const buf = await fs.readFile(abs);
      return { buf, contentType: getMimeType(abs) };
    }
  } catch {
    // continue to fetch
  }

  let response: Response;
  try {
    response = await fetch(remoteUrl, {
      method: "GET",
      redirect: "follow",
      headers: {
        "User-Agent": "TypeParserImageProxy/1.0"
      }
    });
  } catch {
    return null;
  }
  if (!response.ok) return null;

  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  if (!contentType.startsWith("image/")) return null;

  const ab = await response.arrayBuffer();
  const buf = new Uint8Array(ab);
  if (buf.length === 0 || buf.length > 8 * 1024 * 1024) return null;

  const ext = extensionFromRemote(remoteUrl, contentType);
  const outPath = path.join(cacheDir, `${key}${ext}`);
  try {
    await fs.writeFile(outPath, buf);
  } catch {
    // ignore write failure and still return fetched content
  }
  return { buf, contentType };
}

function toResponseBytes(input: Uint8Array): Uint8Array {
  const out = new Uint8Array(input.byteLength);
  out.set(input);
  return out;
}

export async function GET(request: NextRequest) {
  const relPath = request.nextUrl.searchParams.get("p") || "";
  const remoteUrl = request.nextUrl.searchParams.get("u") || "";
  const hasRemoteMode = !!remoteUrl;

  if (hasRemoteMode) {
    if (!isAllowedRemoteUrl(remoteUrl)) {
      return NextResponse.json({ error: "invalid remote url" }, { status: 400 });
    }

    const dataRoot = await resolveDataRoot();
    if (!dataRoot) {
      return NextResponse.json({ error: "data root not found" }, { status: 500 });
    }

    const cached = await readOrCacheRemoteImage(dataRoot, remoteUrl);
    if (!cached) {
      return NextResponse.json({ error: "remote image unavailable" }, { status: 404 });
    }

    return new Response(toResponseBytes(cached.buf) as any, {
      headers: {
        "Content-Type": cached.contentType || "application/octet-stream",
        "Cache-Control": "public, max-age=3600"
      }
    });
  }

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
    return new Response(toResponseBytes(buf) as any, {
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=3600"
      }
    });
  } catch {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
}
