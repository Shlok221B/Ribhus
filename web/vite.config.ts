import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";

const BACKEND = process.env.RIBHUS_DASHBOARD_URL ?? "http://127.0.0.1:8742";

/** Forward the Python dashboard session token into Vite HTML during `npm run dev`. */
function ribhusDevToken(): Plugin {
  const TOKEN_RE = /window\.__RIBHUS_SESSION_TOKEN__\s*=\s*"([^"]+)"/;
  return {
    name: "ribhus:dev-session-token",
    apply: "serve",
    async transformIndexHtml() {
      try {
        const res = await fetch(BACKEND, { headers: { accept: "text/html" } });
        const html = await res.text();
        const match = html.match(TOKEN_RE);
        if (!match) {
          console.warn(
            `[ribhus] No session token at ${BACKEND} — start \`ribhus dashboard\`.`,
          );
          return;
        }
        return [
          {
            tag: "script",
            injectTo: "head",
            children: `window.__RIBHUS_SESSION_TOKEN__="${match[1]}";`,
          },
        ];
      } catch (err) {
        console.warn(
          `[ribhus] Dashboard at ${BACKEND} unreachable (${(err as Error).message})`,
        );
      }
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), ribhusDevToken()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND,
    },
  },
});
