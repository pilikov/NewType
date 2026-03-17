import { promises as fs } from "node:fs";
import path from "node:path";
import Link from "next/link";

import { SourceLinks } from "@/app/source-links";
import { loadNewsSourceMetaMap, newsSourceFaviconUiUrl } from "@/lib/news-source-meta";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type NewsItem = {
  news_id: string;
  source_id: string;
  source_name: string;
  title: string;
  url: string;
  published_at: string | null;
  discovered_at?: string | null;
};

async function resolveProjectRoot(): Promise<string> {
  const cwd = process.cwd();
  // Try multiple locations: cwd/data/news (Vercel Root=web), cwd/web/data/news (Root=repo)
  const newsDirCandidates = [
    path.join(cwd, "data", "news"),
    path.join(cwd, "web", "data", "news"),
  ];

  for (const newsDir of newsDirCandidates) {
    try {
      const st = await fs.stat(newsDir);
      if (!st.isDirectory()) continue;
      const sources = await fs.readdir(newsDir, { withFileTypes: true });
      const hasSources = sources.some(
        (s) => s.isDirectory() && !s.name.startsWith(".") && !/^\d{4}-\d{2}-\d{2}$/.test(s.name)
      );
      if (hasSources) return path.dirname(path.dirname(newsDir));
    } catch {
      continue;
    }
  }
  return cwd;
}

async function loadAllNews(): Promise<NewsItem[]> {
  try {
    const root = await resolveProjectRoot();
    const newsDir = path.join(root, "data", "news");
    const all: NewsItem[] = [];

    const sourceDirs = await fs.readdir(newsDir, { withFileTypes: true });
    for (const source of sourceDirs) {
      if (!source.isDirectory() || source.name.startsWith(".")) continue;
      // Skip date folders at wrong level (e.g. news/2026-03-17 instead of news/monotype/2026-03-17)
      if (/^\d{4}-\d{2}-\d{2}$/.test(source.name)) continue;
      const sourcePath = path.join(newsDir, source.name);
      let dateDirs: { name: string }[];
      try {
        dateDirs = (await fs.readdir(sourcePath, { withFileTypes: true }))
          .filter((d) => d.isDirectory() && /^\d{4}-\d{2}-\d{2}$/.test(d.name))
          .map((d) => ({ name: d.name }));
      } catch {
        continue;
      }
      const sortedDates = dateDirs
        .map((d) => d.name)
        .sort((a, b) => b.localeCompare(a));

      for (const dateDir of sortedDates.slice(0, 7)) {
        const filePath = path.join(sourcePath, dateDir, "all_news.json");
        try {
          const raw = await fs.readFile(filePath, "utf8");
          const items = JSON.parse(raw) as NewsItem[];
          if (Array.isArray(items)) {
            all.push(...items);
          }
        } catch {
          continue;
        }
      }
    }

    const byId = new Map<string, NewsItem>();
    for (const item of all) {
      if (!byId.has(item.news_id)) {
        byId.set(item.news_id, item);
      }
    }

    const result = Array.from(byId.values()).sort((a, b) => {
      const da = a.published_at || "";
      const db = b.published_at || "";
      if (da && db) return db.localeCompare(da); // newest first
      if (da) return -1; // dated before undated
      if (db) return 1;
      return 0;
    });
    const bySource = result.reduce<Record<string, number>>((acc, i) => {
      acc[i.source_id] = (acc[i.source_id] ?? 0) + 1;
      return acc;
    }, {});
    if (process.env.NODE_ENV === "development") {
      console.log("[news] loaded:", result.length, "items, by source:", bySource);
    }
    return result;
  } catch (err) {
    console.error("[news] loadAllNews error:", err);
    return [];
  }
}

// function formatTimeAgo(dateStr: string | null | undefined): string {
//   if (!dateStr) return "";
//   try {
//     const dt = new Date(dateStr);
//     if (Number.isNaN(dt.getTime())) return "";
//     const now = new Date();
//     const diffMs = now.getTime() - dt.getTime();
//     const diffMinutes = Math.floor(diffMs / (1000 * 60));
//     const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
//     const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
//     const diffWeeks = Math.floor(diffDays / 7);
//
//     if (diffMinutes < 1) return "только что";
//     if (diffMinutes < 60) return `${diffMinutes} мин. назад`;
//
//     if (diffHours === 1) return "час назад";
//     if (diffHours >= 2 && diffHours <= 4) return `${diffHours} часа назад`;
//     if (diffHours >= 5 && diffHours <= 20) return `${diffHours} часов назад`;
//     if (diffHours === 21) return "21 час назад";
//     if (diffHours >= 22 && diffHours <= 24) return `${diffHours} часа назад`;
//
//     if (diffDays === 1) return "день назад";
//     if (diffDays >= 2 && diffDays <= 4) return `${diffDays} дня назад`;
//     if (diffDays >= 5 && diffDays <= 6) return `${diffDays} дней назад`;
//     if (diffWeeks === 1) return "неделю назад";
//     if (diffWeeks >= 2 && diffWeeks <= 4) return `${diffWeeks} недели назад`;
//     if (diffWeeks >= 5) return `${diffWeeks} недель назад`;
//
//     return `${diffDays} дней назад`;
//   } catch {
//     return "";
//   }
// }

function formatNewsDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "";
  try {
    const dt = new Date(dateStr);
    if (Number.isNaN(dt.getTime())) return "";
    const day = dt.getDate();
    const month = new Intl.DateTimeFormat("en-US", { month: "short" }).format(dt);
    const year = dt.getFullYear();
    return `${day} ${month} ${year}`;
  } catch {
    return "";
  }
}

function formatTimestamp(item: NewsItem, dateFormatted: string): string {
  if (!dateFormatted) return item.source_name;
  return `${item.source_name} · ${dateFormatted}`;
}

export default async function NewsPage() {
  let news: NewsItem[] = [];
  let sourceMetaMap: Record<string, { name: string; faviconUrl: string | null }> = {};
  try {
    [news, sourceMetaMap] = await Promise.all([
      loadAllNews(),
      loadNewsSourceMetaMap().then((m) =>
        Object.fromEntries(
          Object.entries(m).map(([id, meta]) => [
            id,
            { name: meta.name, faviconUrl: newsSourceFaviconUiUrl(meta) }
          ])
        )
      )
    ]);
  } catch (err) {
    console.error("[news] page error:", err);
  }

  return (
    <main className="w-full">
      <header className="mx-auto mb-8 w-full max-w-7xl pt-0">
        <div className="flex w-full justify-center">
          <Link href="/">
            <img
              src="/Logo.svg"
              alt="Logo"
              className="block h-auto w-full max-w-none"
              width={994}
              height={119}
              decoding="async"
            />
          </Link>
        </div>
        <div className="mt-4 flex w-full justify-center px-4 sm:px-6 lg:px-8">
          <SourceLinks />
        </div>
      </header>

      <div className="min-h-[60vh] w-full px-4 py-8 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-4xl px-2 py-4 sm:px-4">
          {news.length === 0 ? (
            <p className="text-center text-slate-500">Новостей пока нет.</p>
          ) : (
            <div className="flex flex-col gap-4">
              {news.map((item) => {
                const meta = sourceMetaMap[item.source_id];
                const faviconUrl = meta?.faviconUrl ?? null;
                const dateFormatted = formatNewsDate(item.published_at);
                return (
                  <a
                    key={item.news_id}
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block rounded-xl bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
                  >
                    <h3 className="text-lg font-semibold text-slate-900">
                      {item.title}
                    </h3>
                    <p className="mt-2 flex items-center gap-2 text-sm text-slate-500">
                      {faviconUrl ? (
                        <img
                          src={faviconUrl}
                          alt=""
                          className="h-4 w-4 shrink-0 rounded"
                          width={16}
                          height={16}
                        />
                      ) : null}
                      <span>{formatTimestamp(item, dateFormatted)}</span>
                    </p>
                  </a>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
