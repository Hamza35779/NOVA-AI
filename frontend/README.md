# Frontend — NOVA AI chat UI (React 19 + Vite 6 + Tailwind 4 + Tauri 2)

## Dual build outputs (do not confuse)

| Command | Output | Used by |
|---|---|---|
| `npm run build` | `../src/nova_ai/server/static/` | `nova serve` embedded SPA |
| `npm run build:tauri` (`--outDir dist`) | `frontend/dist/` | Tauri `frontendDist` (`src-tauri/tauri.conf.json:7`) |

## Dev

```bash
npm ci
npm run dev        # vite :5173, proxies /v1,/health,/api → :8000
npm run typecheck  # tsc --noEmit
npm run lint       # eslint .
npm run test -- --coverage  # vitest
```

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
