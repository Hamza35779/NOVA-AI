# Frontend — NOVA AI chat UI (React 19 + Vite 6 + Tailwind 4 + Tauri 2)

## Prerequisites

- **Node.js 18+** (CI uses Node 22)
- npm (ships with Node)
- Rust 1.90+ **and platform webview deps** — only for the desktop shell (`npm run tauri dev` / `build:tauri`; Tauri 2 needs Xcode CLT on macOS, WebView2 on Windows, webkit2gtk-4.1 on Linux)
- A running NOVA AI backend for dev mode: `uv run nova serve` (http://localhost:8000)

## Dual build outputs (do not confuse)

| Command | Output | Used by |
|---|---|---|
| `npm run build` | `../src/nova_ai/server/static/` | `nova serve` embedded SPA |
| `npm run build:tauri` (`--outDir dist`) | `frontend/dist/` | Tauri `frontendDist` (`src-tauri/tauri.conf.json:7`) |

> `src/nova_ai/server/static/` is gitignored — a fresh clone must run `npm run build` once before `nova serve` can show the web UI.

## Dev

```bash
npm ci             # or npm install for local dev
npm run dev        # vite :5173, proxies /v1,/health,/api → :8000 (needs `nova serve` running)
npm run build      # emit the embedded SPA into ../src/nova_ai/server/static/
npm run typecheck  # tsc --noEmit
npm run lint       # eslint .
npm run test -- --coverage  # vitest
```

## Desktop (Tauri 2)

```bash
npm run tauri dev     # dev shell with hot reload
npm run build:tauri   # frontend → dist/, then bundle via src-tauri/
```

The Rust workspace is pinned via `rust/rust-toolchain.toml`; `rustup` selects it automatically.

## Notes

- `src/components/Desktop` is excluded from `tsconfig.json` (stale fork — delete or restore per P2).
- PWA `navigateFallbackDenylist` excludes `/v1,/health,/dashboard,/api`.
- `katex` + `recharts` are heavy — lazy-load on math/dashboard routes only.

## Known audit exception (accepted)

- `@vitest/mocker` path-traversal (moderate, dev-only): fix requires
  `vitest@5` breaking upgrade. Deferred — the vulnerable code runs only in
  local `vitest` mock resolution, never in the shipped desktop bundle or
  server runtime. Revisit when vitest 5 stabilizes. (`npm audit` shows
  2 moderate; everything else is fixed.)
