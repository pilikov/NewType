import { NextRequest, NextResponse } from "next/server";

/**
 * По переходу по ссылке с правильным token выполняется слияние ветки crawl/daily в main
 * (слив данных на бой). Нужны env: PUBLISH_SECRET, PUBLISH_GITHUB_TOKEN, GITHUB_REPO (owner/repo).
 */
export async function GET(request: NextRequest) {
  const token = request.nextUrl.searchParams.get("token")?.trim() ?? "";
  const secret = (process.env.PUBLISH_SECRET ?? "").trim();

  if (!secret) {
    return NextResponse.json(
      { error: "PUBLISH_SECRET not set in Vercel. Add it in Project → Settings → Environment Variables and redeploy." },
      { status: 500 }
    );
  }
  if (token !== secret) {
    return NextResponse.json(
      { error: "Forbidden", hint: "Token does not match PUBLISH_SECRET. Check the URL token and Vercel env (no extra spaces)." },
      { status: 403 }
    );
  }

  const ghToken = process.env.PUBLISH_GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!ghToken || !repo) {
    return NextResponse.json(
      { error: "Server misconfiguration: PUBLISH_GITHUB_TOKEN or GITHUB_REPO missing" },
      { status: 500 }
    );
  }

  const [owner, repoName] = repo.split("/").filter(Boolean);
  if (!owner || !repoName) {
    return NextResponse.json(
      { error: "GITHUB_REPO must be owner/repo" },
      { status: 500 }
    );
  }

  try {
    const res = await fetch(
      `https://api.github.com/repos/${owner}/${repoName}/merges`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${ghToken}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          base: "main",
          head: "crawl/daily",
          commit_message: `chore(data): merge daily crawl into main (${new Date().toISOString().slice(0, 10)})`,
        }),
      }
    );

    if (res.status === 204 || res.status === 201) {
      const data = res.status === 201 ? await res.json() : {};
      return NextResponse.json({
        ok: true,
        message: "Merged crawl/daily into main. Vercel will deploy automatically.",
        sha: data.sha,
      });
    }

    const err = await res.text();
    if (res.status === 404) {
      return NextResponse.json(
        { error: "Branch not found (crawl/daily or main)", details: err },
        { status: 404 }
      );
    }
    return NextResponse.json(
      { error: "Merge failed", status: res.status, details: err },
      { status: 502 }
    );
  } catch (e) {
    return NextResponse.json(
      { error: "Merge request failed", details: String(e) },
      { status: 502 }
    );
  }
}
