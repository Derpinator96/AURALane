// Run before the hosted build (vercel.json). Without VITE_API_BASE the client
// calls /api on its own origin, the SPA rewrite answers with index.html, and
// every screen fails with a JSON parse error. Fail the build instead.
const base = process.env.VITE_API_BASE || "";
if (!/^https?:\/\/[^/]+/.test(base)) {
  console.error("VITE_API_BASE is not set to an absolute URL. Set it in Vercel, Project Settings, "
    + "Environment Variables, to the Render API's URL, e.g. https://auralane-api.onrender.com");
  process.exit(1);
}
console.log(`API base: ${base}`);
