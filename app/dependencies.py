from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import Tenant, User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = db.get(User, int(user_id))
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not (user.is_admin or user.is_superadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


def require_superadmin(user: User = Depends(require_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin only")
    return user


def require_reseller_admin(user: User = Depends(require_user)) -> User:
    """User must be reseller admin OR platform superadmin."""
    if not (user.is_reseller_admin or user.is_superadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Reseller admin only")
    return user


def get_current_tenant(user: User = Depends(require_user), db: Session = Depends(get_db)) -> Tenant:
    tenant = db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant missing")
    return tenant


def effective_tenant_id(request: Request, user: User) -> int:
    """If a superadmin is impersonating a tenant, return that tenant_id; else user's own."""
    acting = request.session.get("acting_as_tenant_id")
    if acting and user.is_superadmin:
        try:
            return int(acting)
        except (TypeError, ValueError):
            pass
    return user.tenant_id


def effective_tenant(request: Request, user: User, db: Session) -> Tenant:
    tid = effective_tenant_id(request, user)
    tenant = db.get(Tenant, tid)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant missing")
    return tenant


def is_impersonating(request: Request, user: User) -> bool:
    return user.is_superadmin and bool(request.session.get("acting_as_tenant_id")) \
        and int(request.session["acting_as_tenant_id"]) != user.tenant_id
