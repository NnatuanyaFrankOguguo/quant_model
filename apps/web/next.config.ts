import type { NextConfig } from "next";

/**
 * The API base is read at build and at run time, so the same image can point at a
 * local uvicorn or at a deployed one. It is deliberately server-side only: the browser
 * never talks to the API directly, because a token would then have to live in the
 * browser, and `docs/01` ADR-0006 puts mode derivation on the server.
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,
  env: { QUANT_API_BASE: process.env.QUANT_API_BASE ?? "http://127.0.0.1:8000" },
};

export default nextConfig;
