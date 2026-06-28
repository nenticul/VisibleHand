from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.dependencies import get_db, optional_api_key
from api.models.database import PoliticalEvent
from api.models.schemas import EventRow

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{country_code}", response_model=list[EventRow])
async def get_events(
    country_code: str,
    event_type: Optional[str] = Query(None, description="Filter by type: protest, conflict, election, sanction"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[EventRow]:
    """Return political events for a country."""
    q = db.query(PoliticalEvent).filter(PoliticalEvent.country_code == country_code.upper())
    if event_type:
        q = q.filter(PoliticalEvent.event_type == event_type)
    rows = q.order_by(PoliticalEvent.event_date.desc()).limit(limit).all()
    return [EventRow.model_validate(r) for r in rows]
