from fastapi import APIRouter, Depends, Request

from ..dependencies import require_user
from ..models import User
from ..templating import render

router = APIRouter()


@router.get("/help")
def help_page(request: Request, user: User = Depends(require_user)):
    return render(request, "help.html", user=user, tenant=user.tenant, active="help")
