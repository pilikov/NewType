import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" }
    ]
  },
  outputFileTracingIncludes: {
    "/*": ["./data/**/all_releases.json", "./state/data_coverage.json", "./config/sources.json"]
  },
  outputFileTracingExcludes: {
    "/api/assets": ["./data/**/*", "./state/**/*"]
  }
};

export default nextConfig;
