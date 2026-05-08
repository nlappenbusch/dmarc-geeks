from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_user
from ..ingest import ingest_payload
from ..models import User
from ..templating import render

router = APIRouter(prefix="/upload")


@router.get("")
def upload_form(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return render(request, "upload.html", user=user, tenant=effective_tenant(request, user, db), results=None, active="upload")


@router.post("")
async def upload_submit(
    request: Request,
    files: list[UploadFile] = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    all_results = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        results = ingest_payload(
            db,
            f.filename or "report",
            data,
            tenant_id=effective_tenant_id(request, user),
            auto_create_domain=user.is_admin or user.is_superadmin,
            source="upload",
        )
        for r in results:
            all_results.append({"filename": f.filename, "status": r.status, "message": r.message,
                                 "report_id": r.report_id})
    db.commit()
    return render(request, "upload.html", user=user, tenant=effective_tenant(request, user, db),
                  results=all_results, active="upload")
