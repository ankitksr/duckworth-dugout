import { defineConfig } from "astro/config";
import react from "@astrojs/react";

// ASTRO_BASE controls the URL prefix:
//   "/duckworth-dugout" for GitHub Pages (served under a subpath)
//   "/" (or unset) for Cloudflare Pages (served at root)
export default defineConfig({
  integrations: [react()],
  base: process.env.ASTRO_BASE ?? "/",
});
