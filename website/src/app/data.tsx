/* ─────────────────────────────────────────────────────────────────────────────
   VisibleHand — live data layer

   Pulls real scores, calibration, and methodology from the VisibleHand API and
   merges them over a static snapshot so the marketing site is ALWAYS renderable:
     • API reachable  → live numbers, "LIVE" status, no flash of empty.
     • API unreachable → static archive snapshot, "SNAPSHOT" status.

   Configure the endpoint with VITE_API_BASE (see .env.example).
───────────────────────────────────────────────────────────────────────────── */
import {
  createContext, useContext, useEffect, useState, type ReactNode,
} from "react";

export type Level = "LOW" | "WATCH" | "ELEVATED" | "HIGH" | "SEVERE";
export interface CF {
  name: string;
  score: number;
  level: Level;
  delta: number;
  drivers: [string, string, string];
}

export const LVL_INK: Record<Level, string> = {
  LOW: "#4A6840", WATCH: "#A08A54", ELEVATED: "#9A6749", HIGH: "#8D2F2F", SEVERE: "#101010",
};

/* Static archive snapshot — the fallback dataset and the seed for live merge. */
export const FALLBACK_FILES: Record<string, CF> = {
  ARG:{name:"Argentina",    score:72.1,level:"ELEVATED",delta:+1.4,drivers:["fiscal imbalance","inflation pressure","political friction"]},
  BRA:{name:"Brazil",       score:67.2,level:"ELEVATED",delta:+2.1,drivers:["inflation pressure","fiscal balance","political friction"]},
  CHN:{name:"China",        score:54.8,level:"WATCH",   delta:-0.3,drivers:["governance opacity","trade tension","debt structure"]},
  COL:{name:"Colombia",     score:61.3,level:"ELEVATED",delta:+0.8,drivers:["security conditions","fiscal balance","governance deficit"]},
  EGY:{name:"Egypt",        score:78.4,level:"HIGH",    delta:+4.3,drivers:["debt service","FX pressure","political stability"]},
  GHA:{name:"Ghana",        score:81.2,level:"HIGH",    delta:+3.1,drivers:["debt restructuring","inflation","fiscal deficit"]},
  IND:{name:"India",        score:41.5,level:"WATCH",   delta:-1.2,drivers:["current account","political transition","external debt"]},
  IDN:{name:"Indonesia",    score:43.2,level:"WATCH",   delta:+0.5,drivers:["commodity dependence","inflation","governance"]},
  IRN:{name:"Iran",         score:82.7,level:"HIGH",    delta:+1.8,drivers:["sanctions exposure","governance deficit","inflation"]},
  KEN:{name:"Kenya",        score:58.4,level:"ELEVATED",delta:+2.2,drivers:["debt service","FX pressure","political tension"]},
  MEX:{name:"Mexico",       score:59.7,level:"ELEVATED",delta:+1.1,drivers:["security conditions","fiscal policy","rule of law"]},
  NGA:{name:"Nigeria",      score:75.9,level:"HIGH",    delta:+2.6,drivers:["FX shortage","inflation","oil dependence"]},
  PAK:{name:"Pakistan",     score:84.1,level:"HIGH",    delta:+5.2,drivers:["IMF program stress","political instability","debt service"]},
  PER:{name:"Peru",         score:55.3,level:"ELEVATED",delta:+0.6,drivers:["political instability","fiscal balance","social tension"]},
  PHL:{name:"Philippines",  score:44.8,level:"WATCH",   delta:+0.3,drivers:["external debt","typhoon exposure","governance"]},
  RUS:{name:"Russia",       score:88.3,level:"SEVERE",  delta:+0.9,drivers:["sanctions exposure","capital controls","conflict"]},
  TUR:{name:"Turkey",       score:69.5,level:"ELEVATED",delta:-2.1,drivers:["inflation legacy","FX volatility","current account"]},
  UKR:{name:"Ukraine",      score:91.7,level:"SEVERE",  delta:+1.3,drivers:["active conflict","reconstruction","debt suspension"]},
  USA:{name:"United States",score:22.4,level:"LOW",     delta:+0.7,drivers:["fiscal trajectory","political polarization","debt ceiling"]},
  VEN:{name:"Venezuela",    score:95.2,level:"SEVERE",  delta:+0.2,drivers:["hyperinflation","sanctions","institutional collapse"]},
  ZAF:{name:"South Africa", score:63.8,level:"ELEVATED",delta:+1.9,drivers:["energy crisis","fiscal deficit","unemployment"]},
  ZWE:{name:"Zimbabwe",     score:87.6,level:"HIGH",    delta:+0.4,drivers:["currency instability","debt arrears","governance"]},
};

/* ISO-3 (site) → ISO-2 (API). Only countries the API actually serves are fetched;
   the rest (e.g. Iran, Zimbabwe) keep their snapshot values. */
const ISO3_TO_ISO2: Record<string, string> = {
  ARG:"AR", BRA:"BR", CHN:"CN", COL:"CO", EGY:"EG", GHA:"GH", IND:"IN", IDN:"ID",
  KEN:"KE", MEX:"MX", NGA:"NG", PAK:"PK", PER:"PE", PHL:"PH", RUS:"RU", TUR:"TR",
  UKR:"UA", USA:"US", VEN:"VE", ZAF:"ZA",
};
const ISO2_TO_ISO3: Record<string, string> =
  Object.fromEntries(Object.entries(ISO3_TO_ISO2).map(([a, b]) => [b, a]));
const FETCH_CODES = Object.values(ISO3_TO_ISO2);

export const API_BASE = (
  (import.meta.env.VITE_API_BASE as string | undefined) || "https://api.visiblehand.dev"
).replace(/\/$/, "");

export function levelFromScore(s: number): Level {
  if (s < 30) return "LOW";
  if (s < 50) return "WATCH";
  if (s < 70) return "ELEVATED";
  if (s < 85) return "HIGH";
  return "SEVERE";
}

function humanize(d: string): string {
  return d.replace(/_/g, " ").replace(/\bvs\b/g, "vs").trim();
}

export interface VHMeta {
  live: boolean;
  asOf: string | null;
  version: string | null;
  scored: number | null;
  confidenceFloor: number | null;
  calibration: { auc: number; brier: number; prAuc: number; nEvents: number } | null;
  weights: { economic: number; political: number; nlp: number; governance: number } | null;
}

const OFFLINE_META: VHMeta = {
  live: false, asOf: null, version: null, scored: null,
  confidenceFloor: null, calibration: null, weights: null,
};

export interface VHState { files: Record<string, CF>; meta: VHMeta; sample: any | null; }

async function getJSON(url: string, ms = 7000): Promise<any> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctrl.signal, headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

export async function fetchVHData(base = API_BASE): Promise<VHState> {
  const files: Record<string, CF> = JSON.parse(JSON.stringify(FALLBACK_FILES));
  const meta: VHMeta = { ...OFFLINE_META };
  let sample: any = null;

  const [compareR, rocR, healthR, moversR] = await Promise.allSettled([
    getJSON(`${base}/risk/compare?countries=${FETCH_CODES.join(",")}`),
    getJSON(`${base}/calibration/roc`),
    getJSON(`${base}/health`),
    getJSON(`${base}/risk/movers?days=7&limit=60`),
  ]);

  const liveCodes: string[] = [];
  if (compareR.status === "fulfilled" && Array.isArray(compareR.value)) {
    const confs: number[] = [];
    let latest = "";
    for (const r of compareR.value) {
      const iso3 = ISO2_TO_ISO3[(r.country || "").toUpperCase()];
      if (!iso3) continue;
      const score = Number(r.composite);
      if (!isFinite(score)) continue;
      const drv = Array.isArray(r.top_drivers) && r.top_drivers.length
        ? r.top_drivers.map(humanize)
        : files[iso3].drivers;
      const d3 = [drv[0], drv[1], drv[2]].map((x, i) => x ?? files[iso3].drivers[i]) as [string, string, string];
      files[iso3] = {
        name: r.name || files[iso3].name,
        score: Math.round(score * 10) / 10,
        level: levelFromScore(score),
        delta: files[iso3].delta,          // overwritten from /risk/movers below when live
        drivers: d3,
      };
      liveCodes.push(iso3);
      if (typeof r.confidence === "number") confs.push(r.confidence);
      if (typeof r.updated_at === "string" && r.updated_at > latest) latest = r.updated_at;
      if ((r.country || "").toUpperCase() === "BR") sample = r;
    }
    meta.live = true;
    meta.asOf = latest ? latest.slice(0, 10) : new Date().toISOString().slice(0, 10);
    if (confs.length) {
      const s = [...confs].sort((a, b) => a - b);
      meta.confidenceFloor = Math.round(s[Math.floor(s.length / 2)] * 100) / 100;
    }
  }

  if (moversR.status === "fulfilled" && Array.isArray(moversR.value) && moversR.value.length) {
    const dmap: Record<string, number> = {};
    for (const mv of moversR.value) {
      if (mv && typeof mv.delta === "number") dmap[(mv.country || "").toUpperCase()] = mv.delta;
    }
    // A live 7-day delta window exists → apply real deltas (0 where unchanged).
    for (const iso3 of liveCodes) {
      const iso2 = ISO3_TO_ISO2[iso3];
      if (iso2) files[iso3].delta = dmap[iso2] ?? 0;
    }
  }

  if (rocR.status === "fulfilled" && rocR.value && typeof rocR.value.auc === "number") {
    const v = rocR.value;
    // Only surface calibration in a believable range. A seeded/demo backtest can
    // be degenerate (AUC ≈ 1.0); we don't publish that — the UI then falls back to
    // the documented out-of-sample figures (see METHODOLOGY.md / BENCHMARK).
    if (v.auc >= 0.55 && v.auc <= 0.95) {
      meta.calibration = {
        auc: v.auc, brier: v.brier_score ?? v.brier ?? 0,
        prAuc: v.pr_auc ?? 0, nEvents: v.n_events ?? v.n_crises ?? 0,
      };
    }
  }

  if (healthR.status === "fulfilled" && healthR.value) {
    meta.scored = healthR.value.scored_countries ?? null;
    meta.version = healthR.value.version ?? null;
  }

  return { files, meta, sample };
}

/* ── React context ──────────────────────────────────────────────────────────*/
const VHContext = createContext<VHState>({
  files: FALLBACK_FILES, meta: OFFLINE_META, sample: null,
});

const CACHE_KEY = "vh-data-v1";

export function VHProvider({ children }: { children: ReactNode }) {
  // Stale-while-revalidate: hydrate instantly from this-session cache (so repeat
  // navigations show live numbers with no snapshot flash), then refresh in the
  // background. Falls back to the static snapshot on a cold load.
  const [state, setState] = useState<VHState>(() => {
    try {
      const c = sessionStorage.getItem(CACHE_KEY);
      if (c) { const p = JSON.parse(c); if (p && p.files) return p as VHState; }
    } catch { /* ignore */ }
    return { files: FALLBACK_FILES, meta: OFFLINE_META, sample: null };
  });
  useEffect(() => {
    let alive = true;
    fetchVHData()
      .then((s) => {
        if (!alive) return;
        setState(s);
        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(s)); } catch { /* ignore */ }
      })
      .catch(() => { /* keep cached / snapshot */ });
    return () => { alive = false; };
  }, []);
  return <VHContext.Provider value={state}>{children}</VHContext.Provider>;
}

export const useVH = () => useContext(VHContext);
