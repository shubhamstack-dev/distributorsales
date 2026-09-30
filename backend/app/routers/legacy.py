"""Import the old SQL Server masters. See services/legacy_import.py.

    POST /api/legacy-import      files[] (xlsx / csv), dry_run (default true), year_id
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..services.legacy_import import run_import

router = APIRouter(prefix="/api")


@router.post("/legacy-import")
async def legacy_import(files: list[UploadFile] = File(...), dry_run: bool = Form(True),
                        year_id: int | None = Form(None), db: Session = Depends(get_db)):
    cap, total, got = config.MAX_UPLOAD_MB * 1024 * 1024, 0, []
    for up in files:
        data = await up.read()
        total += len(data)
        if total > cap:
            raise HTTPException(413, f"The files come to more than {config.MAX_UPLOAD_MB} MB. "
                                     f"Send them in two goes.")
        name = up.filename or "file"
        if not name.lower().endswith((".xlsx", ".xlsm", ".csv", ".txt")):
            raise HTTPException(422, f"{name}: send Excel (.xlsx) or CSV files.")
        got.append((name, data))
    try:
        return run_import(db, got, dry_run=dry_run, year_id=year_id)
    except HTTPException:
        raise
    except Exception as e:                       # the report is the useful part
        raise HTTPException(422, f"The import stopped and nothing was saved: {e}")
