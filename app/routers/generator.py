from typing import Optional

from fastapi import APIRouter, Depends, Query, Request

from ..dependencies import require_user
from ..models import User
from ..templating import render

router = APIRouter()


@router.get("/dmarc-generator")
def dmarc_generator(
    request: Request,
    domain: Optional[str] = Query(None),
    user: User = Depends(require_user),
):
    return render(
        request,
        "dmarc_generator.html",
        user=user,
        tenant=user.tenant,
        prefill_domain=(domain or "").strip().lower(),
        active="generator",
    )


@router.get("/spf-generator")
def spf_generator(
    request: Request,
    domain: Optional[str] = Query(None),
    user: User = Depends(require_user),
):
    return render(
        request,
        "spf_generator.html",
        user=user,
        tenant=user.tenant,
        prefill_domain=(domain or "").strip().lower(),
        active="generator",
    )
