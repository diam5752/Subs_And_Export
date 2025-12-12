import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  experimental: {
    turbopack: {
      root: __dirname,
    }
  },
};

export default nextConfig;
