# VisibleHand — Consumer Website

The public landing page for **visiblehand.xyz**. Vite + React 18 + TypeScript +
Tailwind v4. The country scores, ticker, signal panels, methodology weights,
calibration record and API specimen are **pulled live** from the VisibleHand API,
with a static archive snapshot as graceful fallback so the page always renders.

## Live data integration

All data flows through [`src/app/data.tsx`](src/app/data.tsx):

- On mount it calls, in parallel, `GET /risk/compare`, `GET /calibration/roc`,
  and `GET /health` on the API, then merges the results over a static snapshot.
- **API reachable** → live scores/levels/drivers, live country count and
  calibration; the nav shows a green **LIVE · <date>** badge.
- **API down / blocked** → the static snapshot renders unchanged; the nav shows
  an amber **SNAPSHOT** badge. The site never errors or shows empty state.
- ISO-3 (site) ↔ ISO-2 (API) codes are mapped automatically. Countries the API
  doesn't serve (e.g. Iran, Zimbabwe) keep their snapshot values.
- Calibration figures are only shown live when in a believable range; a
  degenerate demo backtest falls back to the documented out-of-sample numbers.

### Configure the endpoint

```bash
cp .env.example .env
# .env
VITE_API_BASE=https://api.visiblehand.dev      # default if unset
# local dev against your own API:
# VITE_API_BASE=http://localhost:8080
```

The API sends `Access-Control-Allow-Origin: *`, so the browser can call it
cross-origin from any deploy domain.

## Develop / build

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # → dist/   (≈197 kB JS / 61 kB gzip)
npm run preview    # serve the production build
```

## Deploy (Vercel)

1. Import `nenticul/VisibleHand` → set **Root Directory** = `website`.
2. Build command `npm run build`, output `dist` (auto-detected).
3. Add env var `VITE_API_BASE` = your API URL (e.g. `https://api.visiblehand.dev`).
4. Add the domain `visiblehand.xyz` in Project → Domains.

DNS (registrar):

```
A      @    76.76.21.21
CNAME  www  cname.vercel-dns.com
```

Point the API subdomain at your API host (Railway/Fly/etc.) and set
`VITE_API_BASE` to match.

## Structure

```
website/
├── index.html              # title/meta/OG, favicon, indexable
├── src/
│   ├── main.tsx
│   ├── styles/             # fonts.css · tailwind.css (v4) · theme.css
│   └── app/
│       ├── App.tsx         # the whole site (sections read live data via useVH)
│       └── data.tsx        # live API client + React context + fallback snapshot
└── public/favicon.svg
```
