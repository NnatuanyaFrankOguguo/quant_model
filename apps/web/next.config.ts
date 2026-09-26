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

  /**
   * Unchanged by default. `next dev` and `next build` both write to `.next`, and while
   * a dev server is serving the preview a production build will overwrite the runtime
   * out from under it - the server then 500s with "Cannot find module ./411.js" until
   * it is restarted, which looks like a broken page rather than a clobbered directory.
   *
   * Setting NEXT_DIST_DIR sends a build somewhere else, so a build can be checked
   * without taking the preview down:
   *
   *     NEXT_DIST_DIR=.next-build npm run build
   */
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
};

export default nextConfig;
