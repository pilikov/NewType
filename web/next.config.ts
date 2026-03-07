import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**" },
      { protocol: "http", hostname: "**" }
    ]
  },
  outputFileTracingIncludes: {
    "/*": ["./data/**/*", "./state/**/*"]
  }
};

export default nextConfig;
