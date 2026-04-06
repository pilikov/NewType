import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" }
    ]
  },
  outputFileTracingIncludes: {
    "/": [
      "./data/*/periods/*/all_releases.json",
      "./data/*/periods/*/new_releases.json",
      "./data/*/20*/all_releases.json",
      "./data/*/20*/new_releases.json",
      "./state/data_coverage.json",
      "./config/sources.json"
    ],
    "/news": [
      "./data/news/*/all_news.json",
      "./config/news_sources.json"
    ]
  },
  outputFileTracingExcludes: {
    "/": [
      "./data/*/20*/assets/**",
      "./data/*/periods/*/assets/**",
      "./data/catalog_snapshot/**",
      "./data/pages/**",
      "./data/js/**",
      "./data/*/_reports/**"
    ],
    "/api/assets": [
      "./data/**",
      "./state/**"
    ]
  }
};

export default nextConfig;
