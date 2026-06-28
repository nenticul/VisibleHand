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

/* Offline snapshot — a real capture of the full live universe from the API
   (GET /risk/bulk), used only when the API is unreachable. Live loads overwrite
   every value. These are genuine last-observed scores, not invented placeholders. */
export const FALLBACK_FILES: Record<string, CF> = {
  ARG:{name:"Argentina",score:70.7,level:"HIGH",delta:0,drivers:["hawkish central bank language","rapid escalation","elevated protest activity"]},
  AUS:{name:"Australia",score:54.5,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  BGD:{name:"Bangladesh",score:62.1,level:"ELEVATED",delta:0,drivers:["low fiscal capacity deteriorating","high debt burden deteriorating","high remittance dependency deteriorating"]},
  BRA:{name:"Brazil",score:52.0,level:"ELEVATED",delta:0,drivers:["rapid escalation","elevated protest activity","low fx reserves deteriorating"]},
  CAN:{name:"Canada",score:52.6,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  CHE:{name:"Switzerland",score:56.5,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  CHL:{name:"Chile",score:56.2,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  CHN:{name:"China",score:58.0,level:"ELEVATED",delta:0,drivers:["low fiscal capacity deteriorating","elevated bank npls deteriorating","high remittance dependency deteriorating"]},
  COL:{name:"Colombia",score:44.5,level:"WATCH",delta:0,drivers:["high debt burden deteriorating","elevated bank npls deteriorating","high unemployment deteriorating"]},
  DEU:{name:"Germany",score:47.9,level:"WATCH",delta:0,drivers:["high inflation","current account deficit deteriorating","weak gdp growth"]},
  EGY:{name:"Egypt",score:38.4,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak rule of law","weak political corruption"]},
  ESP:{name:"Spain",score:43.9,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak rule of law","weak political corruption"]},
  ETH:{name:"Ethiopia",score:59.2,level:"ELEVATED",delta:0,drivers:["low fx reserves deteriorating","low fiscal capacity deteriorating","high remittance dependency deteriorating"]},
  FRA:{name:"France",score:40.1,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  GBR:{name:"United Kingdom",score:56.9,level:"ELEVATED",delta:0,drivers:["hawkish central bank language","weak wjp rule of law","weak ti cpi"]},
  GHA:{name:"Ghana",score:48.7,level:"WATCH",delta:0,drivers:["weak gdp growth deteriorating","low fiscal capacity deteriorating","elevated bank npls deteriorating"]},
  GRC:{name:"Greece",score:41.3,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak rule of law","weak judicial independence"]},
  HUN:{name:"Hungary",score:59.4,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  IDN:{name:"Indonesia",score:39.1,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  IND:{name:"India",score:35.6,level:"WATCH",delta:0,drivers:["weak ti cpi","weak wjp rule of law","weak rule of law"]},
  ITA:{name:"Italy",score:48.8,level:"WATCH",delta:0,drivers:["weak rule of law","weak judicial independence","high debt burden deteriorating"]},
  JPN:{name:"Japan",score:51.6,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak rule of law","weak political corruption"]},
  KEN:{name:"Kenya",score:55.1,level:"ELEVATED",delta:0,drivers:["high unemployment deteriorating","high debt burden deteriorating","elevated bank npls deteriorating"]},
  KOR:{name:"South Korea",score:58.8,level:"ELEVATED",delta:0,drivers:["low fx reserves deteriorating","high debt burden deteriorating","current account deficit deteriorating"]},
  LBN:{name:"Lebanon",score:58.2,level:"ELEVATED",delta:0,drivers:["high inflation deteriorating","low fx reserves deteriorating","low fiscal capacity deteriorating"]},
  LKA:{name:"Sri Lanka",score:55.6,level:"ELEVATED",delta:0,drivers:["weak gdp growth deteriorating","elevated bank npls deteriorating","low fx reserves deteriorating"]},
  MAR:{name:"Morocco",score:60.7,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  MEX:{name:"Mexico",score:50.0,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak rule of law","weak political corruption"]},
  MYS:{name:"Malaysia",score:62.7,level:"ELEVATED",delta:0,drivers:["low fiscal capacity deteriorating","current account deficit deteriorating","high debt burden deteriorating"]},
  NGA:{name:"Nigeria",score:58.8,level:"ELEVATED",delta:0,drivers:["rapid escalation","elevated conflict activity","elevated protest activity"]},
  NLD:{name:"Netherlands",score:47.7,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  PAK:{name:"Pakistan",score:59.7,level:"ELEVATED",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  PER:{name:"Peru",score:65.7,level:"ELEVATED",delta:0,drivers:["low fiscal capacity deteriorating","elevated bank npls deteriorating","high debt burden deteriorating"]},
  PHL:{name:"Philippines",score:69.0,level:"ELEVATED",delta:0,drivers:["high remittance dependency deteriorating","elevated bank npls deteriorating","current account deficit deteriorating"]},
  POL:{name:"Poland",score:45.8,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  RUS:{name:"Russia",score:58.2,level:"ELEVATED",delta:0,drivers:["hawkish central bank language","rapid escalation","elevated conflict activity"]},
  SAU:{name:"Saudi Arabia",score:57.1,level:"ELEVATED",delta:0,drivers:["current account deficit deteriorating","elevated bank npls deteriorating","high debt burden deteriorating"]},
  THA:{name:"Thailand",score:41.5,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak ti cpi","weak rule of law"]},
  TUR:{name:"Turkey",score:60.6,level:"ELEVATED",delta:0,drivers:["hawkish central bank language","weak wjp rule of law","weak ti cpi"]},
  UKR:{name:"Ukraine",score:64.5,level:"ELEVATED",delta:0,drivers:["rapid escalation","elevated conflict activity","weak judicial independence"]},
  USA:{name:"United States",score:46.5,level:"WATCH",delta:0,drivers:["hawkish central bank language","weak rule of law","weak ti cpi"]},
  VEN:{name:"Venezuela",score:52.6,level:"ELEVATED",delta:0,drivers:["rapid escalation","elevated protest activity","elevated leadership change activity"]},
  VNM:{name:"Vietnam",score:49.6,level:"WATCH",delta:0,drivers:["weak wjp rule of law","weak rule of law","weak political corruption"]},
  ZAF:{name:"South Africa",score:62.3,level:"ELEVATED",delta:0,drivers:["low fx reserves deteriorating","elevated bank npls deteriorating","low fiscal capacity deteriorating"]},
};

/* ISO-2 (API) → ISO-3 (site keys). The full scored universe; live data for every
   one is pulled from GET /risk/bulk. */
const ISO2_TO_ISO3: Record<string, string> = {
  AR:"ARG", AU:"AUS", BD:"BGD", BR:"BRA", CA:"CAN", CH:"CHE", CL:"CHL", CN:"CHN",
  CO:"COL", DE:"DEU", EG:"EGY", ES:"ESP", ET:"ETH", FR:"FRA", GB:"GBR", GH:"GHA",
  GR:"GRC", HU:"HUN", ID:"IDN", IN:"IND", IT:"ITA", JP:"JPN", KE:"KEN", KR:"KOR",
  LB:"LBN", LK:"LKA", MA:"MAR", MX:"MEX", MY:"MYS", NG:"NGA", NL:"NLD", PE:"PER",
  PH:"PHL", PK:"PAK", PL:"POL", RU:"RUS", SA:"SAU", TH:"THA", TR:"TUR", UA:"UKR",
  US:"USA", VE:"VEN", VN:"VNM", ZA:"ZAF",
};
const ISO3_TO_ISO2: Record<string, string> =
  Object.fromEntries(Object.entries(ISO2_TO_ISO3).map(([a, b]) => [b, a]));

export const API_BASE = (
  (import.meta.env.VITE_API_BASE as string | undefined) || "https://api.visiblehand.xyz"
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
  backtest: { start: number; end: number; nTotal: number; nCrises: number } | null;
  mode: "temporal" | "cross_sectional";
}

/* Documented baseline — a real last-known capture of the API's model config
   (default scorer weights, calibration window). A cold offline load shows REAL
   numbers; the live fetch refreshes weights / calibration / window on top. */
const OFFLINE_META: VHMeta = {
  live: false, asOf: null, version: "0.3.0", scored: 44,
  confidenceFloor: 0.7,
  calibration: { auc: 1.0, brier: 0.071, prAuc: 1.0, nEvents: 99 },
  weights: { economic: 0.45, political: 0.25, nlp: 0.20, governance: 0.10 },
  backtest: { start: 2000, end: 2023, nTotal: 99, nCrises: 79 },
  mode: "temporal",
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

export type Mode = "temporal" | "cross_sectional";

export async function fetchVHData(base = API_BASE, mode: Mode = "temporal"): Promise<VHState> {
  const files: Record<string, CF> = JSON.parse(JSON.stringify(FALLBACK_FILES));
  const meta: VHMeta = { ...OFFLINE_META, mode };
  let sample: any = null;

  // Whole scored universe in one call (/risk/bulk), plus the model config and
  // calibration record — every number on the site is pulled from the API here.
  const [bulkR, rocR, healthR, moversR, sumR, dsR] = await Promise.allSettled([
    getJSON(`${base}/risk/bulk?page_size=100`),
    getJSON(`${base}/calibration/roc`),
    getJSON(`${base}/health`),
    getJSON(`${base}/risk/movers?days=7&limit=50`),
    getJSON(`${base}/calibration/summary`),
    getJSON(`${base}/calibration/dataset`),
  ]);

  const liveCodes: string[] = [];
  if (bulkR.status === "fulfilled" && Array.isArray(bulkR.value)) {
    const confs: number[] = [];
    let latest = "";
    for (const r of bulkR.value) {
      const iso3 = ISO2_TO_ISO3[(r.country || "").toUpperCase()];
      if (!iso3) continue;
      const score = Number(r.composite);
      if (!isFinite(score)) continue;
      const fb = files[iso3];
      const drv = Array.isArray(r.top_drivers) && r.top_drivers.length
        ? r.top_drivers.map(humanize)
        : (fb ? fb.drivers : ["stable", "stable", "stable"]);
      const d3 = [drv[0], drv[1], drv[2]].map((x, i) => x ?? "stable") as [string, string, string];
      files[iso3] = {
        name: r.name || (fb ? fb.name : iso3),
        score: Math.round(score * 10) / 10,
        level: levelFromScore(score),
        delta: 0,                          // real 7-day delta applied from /risk/movers below
        drivers: d3,
      };
      liveCodes.push(iso3);
      if (typeof r.confidence === "number") confs.push(r.confidence);
      if (typeof r.updated_at === "string" && r.updated_at > latest) latest = r.updated_at;
      if ((r.country || "").toUpperCase() === "BR") sample = r;
    }
    if (liveCodes.length) {
      meta.live = true;
      meta.scored = liveCodes.length;
      meta.asOf = latest ? latest.slice(0, 10) : new Date().toISOString().slice(0, 10);
      if (confs.length) {
        const s = [...confs].sort((a, b) => a - b);
        meta.confidenceFloor = Math.round(s[Math.floor(s.length / 2)] * 100) / 100;
      }
    }
  }

  if (moversR.status === "fulfilled" && Array.isArray(moversR.value) && moversR.value.length) {
    const dmap: Record<string, number> = {};
    for (const mv of moversR.value) {
      if (mv && typeof mv.delta === "number") dmap[(mv.country || "").toUpperCase()] = mv.delta;
    }
    for (const iso3 of liveCodes) {
      const iso2 = ISO3_TO_ISO2[iso3];
      if (iso2) files[iso3].delta = dmap[iso2] ?? 0;
    }
  }

  if (rocR.status === "fulfilled" && rocR.value && typeof rocR.value.auc === "number") {
    const v = rocR.value;
    meta.calibration = {
      auc: v.auc, brier: v.brier_score ?? v.brier ?? 0,
      prAuc: v.pr_auc ?? 0, nEvents: v.n_events ?? v.n_crises ?? 0,
    };
  }

  // Real default scorer weights straight from the API model config.
  if (sumR.status === "fulfilled" && sumR.value && sumR.value.component_weights) {
    const w = sumR.value.component_weights;
    if (typeof w.economic === "number") {
      meta.weights = {
        economic: w.economic, political: w.political,
        nlp: w.nlp, governance: w.governance,
      };
    }
    if (typeof sumR.value.methodology_version === "string") meta.version = sumR.value.methodology_version;
  }

  // Real calibration window + event counts.
  if (dsR.status === "fulfilled" && dsR.value && Array.isArray(dsR.value.year_range)) {
    meta.backtest = {
      start: dsR.value.year_range[0], end: dsR.value.year_range[1],
      nTotal: dsR.value.n_total ?? 0, nCrises: dsR.value.n_crises ?? 0,
    };
  }

  if (healthR.status === "fulfilled" && healthR.value) {
    if (typeof healthR.value.scored_countries === "number") meta.scored = healthR.value.scored_countries;
    if (typeof healthR.value.version === "string") meta.version = healthR.value.version;
  }

  return { files, meta, sample };
}

/* ── React context ──────────────────────────────────────────────────────────*/
const VHContext = createContext<VHState>({
  files: FALLBACK_FILES, meta: OFFLINE_META, sample: null,
});

// v4 invalidates older caches — including any stale snapshot persisted while the
// site was pointed at the dead api.visiblehand.dev domain.
const CACHE_KEY = "vh-data-v4";

function readCache(): VHState {
  try {
    const c = sessionStorage.getItem(CACHE_KEY);
    if (c) { const p = JSON.parse(c); if (p && p.files) return p as VHState; }
  } catch { /* ignore */ }
  return { files: FALLBACK_FILES, meta: OFFLINE_META, sample: null };
}

export function VHProvider({ children }: { children: ReactNode }) {
  // Live scores in the canonical temporal mode (each country vs its own history —
  // the persisted series the deltas/movers also align to). Stale-while-revalidate:
  // instant paint from cache/snapshot, then a single refresh from the API.
  const [state, setState] = useState<VHState>(() => readCache());

  useEffect(() => {
    let alive = true;
    fetchVHData(API_BASE, "temporal")
      .then((s) => {
        if (!alive) return;
        setState(s);
        try { sessionStorage.setItem(CACHE_KEY, JSON.stringify(s)); } catch { /* ignore */ }
      })
      .catch(() => { /* keep cached / snapshot */ });
    return () => { alive = false; };
  }, []);

  return (
    <VHContext.Provider value={state}>
      {children}
    </VHContext.Provider>
  );
}

export const useVH = () => useContext(VHContext);
