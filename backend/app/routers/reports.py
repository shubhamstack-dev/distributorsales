"""Reports menu.

    GET /api/reports/nepal-analyzer?month=September&year=2026
        NepalAnalyzerReports_September2026.xlsx: the 18 sheets of the old
        Reports/NewNepal_Analyser.aspx (app/reports/nepal_analyzer.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..reports import nepal_analyzer as NA

router = APIRouter(prefix="/api/reports")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/nepal-analyzer")
def nepal_analyzer(month: str = Query(""), year: str = Query(""), db: Session = Depends(get_db)):
    m = next((x for x in NA.MONTHS if x.lower() == month.strip().lower()), None)
    if not m:
        raise HTTPException(400, "Select the month.")
    try:
        y = int(year)
    except ValueError:
        raise HTTPException(400, "Select the year.")
    if not 2000 <= y <= 2100:
        raise HTTPException(400, "Select the year.")
    name, data = NA.report(db, m, y)
    return Response(data, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
