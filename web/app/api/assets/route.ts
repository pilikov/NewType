import { NextRequest, NextResponse } from "next/server";

// Remote image proxy — no fs imports to avoid Vercel bundling data/ (400MB+)

function isAllowedRemoteUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export async function GET(request: NextRequest) {
  const remoteUrl = request.nextUrl.searchParams.get("u") || "";

  if (!remoteUrl) {
    return NextResponse.json({ error: "missing ?u= parameter" }, { status: 400 });
  }

  if (!isAllowedRemoteUrl(remoteUrl)) {
    return NextResponse.json({ error: "invalid remote url" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await fetch(remoteUrl, {
      method: "GET",
      redirect: "follow",
      headers: { "User-Agent": "TypeParserImageProxy/1.0" }
    });
  } catch {
    return NextResponse.json({ error: "remote image unavailable" }, { status: 502 });
  }

  if (!response.ok) {
    return NextResponse.json({ error: "remote image unavailable" }, { status: 404 });
  }

  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  if (!contentType.startsWith("image/")) {
    return NextResponse.json({ error: "not an image" }, { status: 400 });
  }

  const ab = await response.arrayBuffer();
  if (ab.byteLength === 0 || ab.byteLength > 8 * 1024 * 1024) {
    return NextResponse.json({ error: "image too large or empty" }, { status: 400 });
  }

  return new Response(ab, {
    headers: {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=3600"
    }
  });
}
