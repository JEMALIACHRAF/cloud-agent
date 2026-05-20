"""Audit log router."""
from fastapi import APIRouter, Query
from core.audit import AuditLogger

router = APIRouter()
audit = AuditLogger()

@router.get("/logs")
async def get_logs(limit: int = Query(default=200, le=500), run_id: str = None):
    logs = audit.read(limit=limit, run_id=run_id)
    return {"logs": logs, "count": len(logs)}
