# Earth Scope — frontend

React 19 + TypeScript + Vite + Tailwind CSS v4, with Recharts, React Leaflet and React Router. Linted with Oxlint.

```powershell
npm install
npm run dev       # http://localhost:5173 (proxies /api to http://127.0.0.1:8000)
npm run lint      # Oxlint
npm run build     # type-check + production build
npm run preview   # serve the build (also proxies /api)
```

The backend must be running for live data. See the root [README](../README.md) for full setup, architecture and API docs.

Source layout: `src/pages` (routes), `src/components/{layout,dashboard,map,charts,analysis,common}`,
`src/services/api.ts` (all HTTP calls), `src/hooks`, `src/types/api.ts` (mirrors backend schemas), `src/utils`, `src/constants`.
