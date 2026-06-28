from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.dependencies import get_db, optional_api_key
from api.models.database import Indicator
from api.models.schemas import IndicatorRow

router = APIRouter(prefix="/indicators", tags=["indicators"])


@router.get("/{country_code}", response_model=list[IndicatorRow])
async def get_indicators(
    country_code: str,
    metric: Optional[str] = Query(None, description="Filter by metric name, e.g. gdp_growth"),
    from_date: Optional[str] = Query(None, alias="from", description="ISO date lower bound"),
    to_date: Optional[str] = Query(None, alias="to", description="ISO date upper bound"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    _key: Optional[str] = Depends(optional_api_key),
) -> list[IndicatorRow]:
    """Return raw indicator time-series for a country."""
    q = db.query(Indicator).filter(Indicator.country_code == country_code.upper())
    if metric:
        q = q.filter(Indicator.metric == metric)
    if from_date:
        q = q.filter(Indicator.date >= from_date)
    if to_date:
        q = q.filter(Indicator.date <= to_date)
    rows = q.order_by(Indicator.date.desc()).limit(limit).all()
    return [IndicatorRow.model_validate(r) for r in rows]
