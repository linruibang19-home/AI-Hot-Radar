import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Compose runs the web app from a slim runtime image; standalone output keeps
  // that image small and avoids shipping the full node_modules tree.
  output: "standalone",
  reactStrictMode: true,
  env: {
    API_BASE_URL: process.env.API_BASE_URL ?? "http://core-api:8080",
  },
};

export default nextConfig;
