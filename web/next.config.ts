import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" }
    ]
  },
  outputFileTracingIncludes: {
    "/*": [
      // Periods (weekly aggregated data) — small, needed for all sources
      "./data/*/periods/*/all_releases.json",
      "./data/*/periods/*/new_releases.json",
      // Daily dirs — only JSON, no assets (images can be 100MB+)
      "./data/*/20*/all_releases.json",
      "./data/*/20*/new_releases.json",
      // News
      "./data/news/*/all_news.json",
      // Config and state
      "./state/data_coverage.json",
      "./config/sources.json",
      "./config/news_sources.json"
    ]
  },
  outputFileTracingExcludes: {
    "/*": [
      // Exclude downloaded assets (images, fonts) — huge and not read by SSR
      "./data/*/20*/assets/**",
      "./data/*/periods/*/assets/**",
      // Exclude catalog snapshots, pages, JS dumps — not used by the site
      "./data/catalog_snapshot/**",
      "./data/pages/**",
      "./data/js/**",
      // Exclude reports
      "./data/*/_reports/**"
    ]
  }
};

export default nextConfig;
