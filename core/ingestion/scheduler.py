"""
Scheduler entry point — called by APScheduler at 2am UTC daily.

Pipeline order is intentional: WDI/FRED/IMF first (economic base), then
ILO/BIS/IMF FSI (V3 additional indicators), then political events (GDELT
first as no-key, ACLED second as keyed), then NLP (central banks).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from api.models.database import SessionLocal, IngestionLog

log = logging.getLogger(__name__)


async def _run_with_log(name: str, coro) -> None:
    """Run an ingestion coroutine and write a row to ingestion_log."""
    db = SessionLocal()
    started = datetime.now(timezone.utc)
    try:
        await coro
        db.add(IngestionLog(
            source=name,
            country_code=None,
            status="success",
            records_fetched=None,
            error_message=None,
            ran_at=started,
        ))
        db.commit()
        log.info("ingestion [%s] completed", name)
    except Exception as exc:
        log.exception("ingestion [%s] failed: %s", name, exc)
        db.add(IngestionLog(
            source=name,
            country_code=None,
            status="error",
            records_fetched=0,
            error_message=str(exc)[:500],
            ran_at=started,
        ))
        db.commit()
    finally:
        db.close()


async def run_all_ingestion() -> None:
    """Run all ingestion pipelines sequentially to respect rate limits."""
    from core.ingestion.worldbank import ingest_world_bank
    from core.ingestion.fred import ingest_fred
    from core.ingestion.imf import ingest_imf
    from core.ingestion.ilo import ingest_ilo
    from core.ingestion.bis import ingest_bis
    from core.ingestion.imf_fsi import ingest_imf_fsi
    from core.ingestion.gdelt import ingest_gdelt
    from core.ingestion.acled import ingest_acled
    from core.ingestion.centralbank import ingest_central_banks

    pipeline = [
        ("worldbank",   ingest_world_bank()),
        ("fred",        ingest_fred()),
        ("imf_weo",     ingest_imf()),
        ("ilostat",     ingest_ilo()),
        ("bis",         ingest_bis()),
        ("imf_fsi",     ingest_imf_fsi()),
        ("gdelt",       ingest_gdelt()),
        ("acled",       ingest_acled()),
        ("centralbank", ingest_central_banks()),
    ]
    for name, coro in pipeline:
        await _run_with_log(name, coro)

    log.info("full ingestion cycle complete at %s", datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    asyncio.run(run_all_ingestion())
