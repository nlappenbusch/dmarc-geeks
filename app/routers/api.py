"""External HTTP ingestion endpoint.

Auth via Bearer token. Token format: `<prefix>.<secret>` where prefix begins with `dmk_`.
The secret is stored only as bcrypt hash; lookup is by prefix, then verify.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..database import get_db
from ..ingest import ingest_payload
from ..models import ApiKey, Tenant
from ..security import verify_password
from ..webhooks import emit as emit_webhook

router = APIRouter(prefix="/api/v1")


def _resolve_tenant(authorization: str | None, db: Session, request: Request | None = None) -> Tenant:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    if "." not in token or not token.startswith("dmk_"):
        raise HTTPException(status_code=401, detail="Invalid token format")
    prefix, secret = token.split(".", 1)
    key = db.execute(
        select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
    ).scalars().first()
    if not key or not verify_password(secret, key.secret_hash):
        raise HTTPException(status_code=401, detail="Invalid or revoked token")
    tenant = db.get(Tenant, key.tenant_id)
    if not tenant:
        raise HTTPException(status_code=401, detail="Tenant not found")
    key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return tenant


@router.post("/reports")
async def api_upload_report(
    request: Request,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    tenant = _resolve_tenant(request.headers.get("authorization"), db, request)
    out = []
    new_report_ids: list[int] = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        results = ingest_payload(
            db,
            f.filename or "report",
            data,
            tenant_id=tenant.id,
            auto_create_domain=True,
            source="api",
        )
        for r in results:
            out.append({"filename": f.filename, "status": r.status, "message": r.message,
                         "report_id": r.report_id})
            if r.status == "ok" and r.report_id:
                new_report_ids.append(r.report_id)
    audit.record(db, action="api.upload", tenant_id=tenant.id,
                 details={"files": len(files), "imported": len(new_report_ids)},
                 ip=request.client.host if request.client else None)
    db.commit()
    for rid in new_report_ids:
        emit_webhook(tenant.id, "report.imported", {"report_id": rid})
    return {"results": out}


@router.get("/healthz")
def healthz():
    return {"ok": True}
