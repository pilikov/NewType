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
      "./data/**/all_releases.json",
      "./data/news/**/all_news.json",
      "./state/data_coverage.json",
      "./config/sources.json",
      "./config/news_sources.json"
    ]
  },
  outputFileTracingExcludes: {
    // Exclude large data/state from api/assets bundle (Vercel 300MB limit)
    "/api/assets": [
      "./data/**/*",
      "./state/**/*",
      "../data/**/*",
      "../state/**/*"
    ]
  }
};

export default nextConfig;
