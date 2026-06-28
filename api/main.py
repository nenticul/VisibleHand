import logging
import logging.config
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy import text

from api.config import get_settings
from api.models.database import SessionLocal
from api.models.schemas import HealthResponse
from api.observability import configure_observability, PrometheusMiddleware
from api.routers import risk, indicators, events, dashboard
from api.routers import governance as governance_router
from api.routers import nlp as nlp_router
from api.routers import calibration as calibration_router
from api.routers import worldstate as worldstate_router

settings = get_settings()

# ── Logging ──────────────────────────────────────────────────────────────────
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)-8s %(name)s %(message)s",
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
    "root": {"level": settings.log_level, "handlers": ["console"]},
}
logging.config.dictConfig(LOGGING_CONFIG)
log = logging.getLogger("visiblehand")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_observability(settings)
    log.info("VisibleHand starting (env=%s version=0.3.0)", settings.environment)
    scheduler = None
    if settings.ingestion_enabled:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from core.ingestion.scheduler import run_all_ingestion

            scheduler = AsyncIOScheduler()
            scheduler.add_job(run_all_ingestion, "cron", hour=settings.ingestion_hour_utc, minute=0)
            scheduler.start()
            log.info("ingestion scheduler started (daily %02d:00 UTC)", settings.ingestion_hour_utc)
        except ImportError:
            log.warning("apscheduler not installed — scheduler disabled")
    yield
    if scheduler:
        scheduler.shutdown()
    log.info("VisibleHand shut down cleanly")


app = FastAPI(
    title="VisibleHand",
    version="0.3.0",
    summary="Open, programmable political-economic country risk scoring.",
    description=(
        "Scores any country 0–100 by combining live macroeconomic data "
        "(World Bank, FRED, IMF, ILO, BIS), political event feeds (GDELT/ACLED), and "
        "FinBERT-based NLP analysis of central-bank statements. Every score "
        "ships a confidence figure, Bayesian 95% CI, signed driver attributions, "
        "and a plain-language methodology string. Commercial equivalents cost "
        "$15–50k/year — this is free and open-source."
    ),
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json",
    contact={"name": "VisibleHand", "url": "https://github.com/YOUR_USERNAME/visiblehand"},
    license_info={"name": "MIT"},
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
)
app.add_middleware(PrometheusMiddleware)

# ── Rate limiting ─────────────────────────────────────────────────────────────
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    log.info("rate limiting enabled (%s per IP)", settings.rate_limit)
except ImportError:
    log.warning("slowapi not installed — rate limiting disabled")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    if request.url.path not in ("/health", "/health/live", "/health/ready", "/favicon.ico"):
        log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(risk.router)
app.include_router(indicators.router)
app.include_router(events.router)
app.include_router(dashboard.router)
app.include_router(governance_router.router)
app.include_router(nlp_router.router)
app.include_router(calibration_router.router)
app.include_router(worldstate_router.router)


# ── Health endpoints ──────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Combined liveness + DB connectivity probe (legacy, kept for backward compat)."""
    db_status = "ok"
    scored = 0
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        scored = db.execute(
            text("SELECT COUNT(DISTINCT country_code) FROM country_scores")
        ).scalar() or 0
        db.close()
    except Exception as exc:
        log.warning("health check DB error: %s", exc)
        db_status = "unavailable"
    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        version="0.3.0",
        database=db_status,
        scored_countries=int(scored),
    )


@app.get("/health/live", tags=["meta"])
async def health_live() -> dict:
    """Kubernetes liveness probe — returns 200 if the process is alive."""
    return {"status": "alive"}


@app.get("/health/ready", tags=["meta"])
async def health_ready() -> JSONResponse:
    """Kubernetes readiness probe — returns 200 only when DB is reachable."""
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        log.warning("readiness check failed: %s", exc)
        return JSONResponse({"status": "not_ready", "detail": str(exc)}, status_code=503)


@app.get("/health/scores", tags=["meta"])
async def health_scores() -> dict:
    """Scored country count and staleness check."""
    try:
        db = SessionLocal()
        scored = int(db.execute(
            text("SELECT COUNT(DISTINCT country_code) FROM country_scores")
        ).scalar() or 0)
        from sqlalchemy import func
        from api.models.database import CountryScore
        latest = db.query(func.max(CountryScore.computed_at)).scalar()
        db.close()
        return {
            "scored_countries": scored,
            "latest_score_at": latest.isoformat() if latest else None,
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Custom API docs (Mac OS System 6/7 aesthetic) ────────────────────────────

_DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>API Docs — VisibleHand</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    font-family:-apple-system,"Segoe UI",Geneva,Verdana,Arial,sans-serif;
    font-size:12px;background:#808080;color:#000;min-height:100vh;
  }
  /* ── Mac menubar ── */
  .menubar{
    height:20px;background:#fff;border-bottom:1px solid #000;
    display:flex;align-items:center;font-size:12px;font-weight:bold;
    padding:0 4px;position:sticky;top:0;z-index:9999;
  }
  .menubar .apple{font-size:14px;margin-right:4px;padding:0 6px}
  .menubar .mi{padding:0 8px;cursor:default}
  .menubar .mi:hover{background:#000;color:#fff}
  .menubar .mi-r{margin-left:auto;font-weight:normal;font-size:10px;color:#555;padding:0 8px}
  /* ── Mac desktop + window ── */
  .desktop{padding:12px 16px 20px;min-height:calc(100vh - 20px)}
  .window{background:#fff;border:1px solid #000;box-shadow:2px 2px 0 #000;max-width:1200px;margin:0 auto}
  /* ── Titlebar ── */
  .titlebar{
    height:20px;
    background:repeating-linear-gradient(to bottom,#000 0,#000 1px,#fff 1px,#fff 2px);
    border-bottom:1px solid #000;display:flex;align-items:center;padding:0 4px;gap:4px;
  }
  .closebox{
    width:13px;height:13px;border:1px solid #000;background:#fff;flex:none;
    cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:9px;
  }
  .closebox:hover{background:#000;color:#fff}
  .titletext{
    flex:1;text-align:center;font-size:11px;font-weight:bold;
    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
    text-shadow:1px 1px 0 #fff;
  }
  .zoombox{width:13px;height:13px;border:1px solid #000;background:#fff;flex:none;
    display:flex;align-items:center;justify-content:center;font-size:8px;cursor:pointer}
  /* ── Status bar ── */
  .statbar{
    height:18px;background:#e8e8e8;border-bottom:1px solid #aaa;
    display:flex;align-items:center;padding:0 8px;font-size:10px;
    justify-content:space-between;
  }
  .statbar a{font-size:10px;color:#000;text-decoration:none}
  .statbar a:hover{text-decoration:underline}
  /* ── Swagger container ── */
  #swagger-wrap{padding:0;overflow-x:auto}

  /* ── Swagger UI overrides ── */
  .swagger-ui .topbar{display:none !important}
  .swagger-ui .info{padding:12px 16px;border-bottom:1px solid #ccc;margin:0 !important}
  .swagger-ui .info .title{font-size:14px;font-weight:bold;font-family:inherit}
  .swagger-ui .info .description{font-size:11px}
  .swagger-ui .scheme-container{
    background:#e8e8e8 !important;border-bottom:1px solid #aaa;
    padding:6px 16px !important;box-shadow:none !important;
  }
  .swagger-ui .btn{border-radius:0 !important;font-family:inherit !important}
  .swagger-ui .btn.execute{
    background:#000 !important;color:#fff !important;
    border-color:#000 !important;border-radius:0 !important;
  }
  .swagger-ui .btn.execute:hover{background:#333 !important}
  .swagger-ui .opblock-tag{
    font-family:inherit !important;font-size:12px !important;font-weight:bold;
    border-bottom:1px solid #ccc !important;background:#f5f5f5 !important;
    border-radius:0 !important;margin:0 !important;
  }
  .swagger-ui .opblock-tag:hover{background:#e8e8e8 !important}
  .swagger-ui .opblock{
    border-radius:0 !important;border:1px solid #ccc !important;
    margin:4px 0 !important;box-shadow:none !important;
  }
  .swagger-ui .opblock .opblock-summary{border-radius:0 !important}
  .swagger-ui .opblock.opblock-get .opblock-summary-method{background:#336 !important;border-radius:0 !important}
  .swagger-ui .opblock.opblock-post .opblock-summary-method{background:#363 !important;border-radius:0 !important}
  .swagger-ui .opblock.opblock-delete .opblock-summary-method{background:#633 !important;border-radius:0 !important}
  .swagger-ui .opblock-summary-method{
    font-family:Monaco,"Courier New",monospace !important;
    font-size:11px !important;border-radius:0 !important;
    min-width:60px !important;text-align:center !important;
  }
  .swagger-ui .opblock-summary-path,.swagger-ui .opblock-summary-path a{
    font-family:Monaco,"Courier New",monospace !important;font-size:11px !important;
  }
  .swagger-ui select,.swagger-ui input{border-radius:0 !important;font-family:inherit !important}
  .swagger-ui table{font-family:inherit !important;font-size:11px !important}
  .swagger-ui .model{font-family:Monaco,"Courier New",monospace !important;font-size:10px !important}
  .swagger-ui .response-col_status{font-family:Monaco,monospace !important;font-size:11px !important}
  .swagger-ui .markdown p,.swagger-ui .renderedMarkdown p{font-size:11px !important}
  .swagger-ui section.models{border-radius:0 !important;border:1px solid #ccc !important}
  .swagger-ui section.models h4{font-family:inherit !important;border-radius:0 !important}
  /* Tab bar at bottom */
  .tabbar{
    display:flex;border-top:2px solid #000;background:#e8e8e8;
    font-size:11px;font-weight:bold;
  }
  .tab{
    padding:4px 12px;border-right:1px solid #000;cursor:pointer;
    text-decoration:none;color:#000;border-top:none;
  }
  .tab:hover,.tab.on{background:#000;color:#fff}
  .tab-gap{flex:1}
</style>
</head>
<body>
<div class="menubar">
  <span class="apple">&#x2318;</span>
  <span class="mi">File</span>
  <span class="mi">Edit</span>
  <span class="mi">Go</span>
  <span class="mi-r">VisibleHand v0.3</span>
</div>
<div class="desktop">
<div class="window">
  <div class="titlebar">
    <div class="closebox" onclick="location='/'">&#x2715;</div>
    <div class="titletext">VisibleHand — Interactive API Explorer</div>
    <div class="zoombox">&#x25B8;</div>
  </div>
  <div class="statbar">
    <span>Swagger UI 5 · OpenAPI 3.1 · Base URL: /</span>
    <a href="/api">Human-readable API reference &#x25B8;</a>
  </div>
  <div id="swagger-wrap"></div>
  <div class="tabbar">
    <a class="tab" href="/">Browse</a>
    <a class="tab" href="/dashboard">Dashboard</a>
    <a class="tab on" href="/docs">API</a>
    <a class="tab" href="/methodology">Methodology</a>
    <span class="tab-gap"></span>
    <a class="tab" href="/">Exit</a>
  </div>
</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
  SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-wrap",
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    deepLinking: true,
    defaultModelsExpandDepth: 1,
    defaultModelExpandDepth: 1,
    displayRequestDuration: true,
    tryItOutEnabled: true,
    filter: true,
  });
</script>
</body>
</html>"""


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def custom_docs() -> HTMLResponse:
    return HTMLResponse(_DOCS_HTML)


# ── Prometheus metrics endpoint ───────────────────────────────────────────────

@app.get("/metrics", tags=["meta"], include_in_schema=False)
async def metrics() -> PlainTextResponse:
    """Prometheus scrape endpoint. Returns 503 if prometheus_client not installed."""
    if not getattr(settings, "prometheus_enabled", True):
        return PlainTextResponse("# metrics disabled\n", status_code=503)
    try:
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
    except ImportError:
        return PlainTextResponse("# prometheus_client not installed\n", status_code=503)
