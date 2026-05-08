from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..dependencies import effective_tenant, effective_tenant_id, require_admin
from ..imap_poller import is_polling, poll_in_background
from ..models import Mailbox, User
from ..security import encrypt_secret
from ..templating import render

router = APIRouter(prefix="/mailboxes")


def _get(db: Session, mailbox_id: int, tid: int) -> Mailbox:
    mb = db.get(Mailbox, mailbox_id)
    if not mb or mb.tenant_id != tid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")
    return mb


@router.get("")
def list_mailboxes(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mailboxes = db.execute(
        select(Mailbox).where(Mailbox.tenant_id == effective_tenant_id(request, user)).order_by(Mailbox.label)
    ).scalars().all()
    polling_ids = {m.id for m in mailboxes if is_polling(m.id)}
    return render(request, "mailboxes.html", user=user, tenant=effective_tenant(request, user, db),
                  mailboxes=mailboxes, polling_ids=polling_ids, active="mailboxes")


@router.post("")
def create_mailbox(
    request: Request,
    label: str = Form(...),
    host: str = Form(...),
    port: int = Form(993),
    use_ssl: bool = Form(False),
    username: str = Form(...),
    password: str = Form(...),
    folder: str = Form("INBOX"),
    move_to_folder: str = Form(""),
    enabled: bool = Form(False),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mb = Mailbox(
        tenant_id=effective_tenant_id(request, user),
        label=label.strip(),
        host=host.strip(),
        port=port,
        use_ssl=use_ssl,
        username=username.strip(),
        password_encrypted=encrypt_secret(password),
        folder=folder.strip() or "INBOX",
        move_to_folder=(move_to_folder.strip() or None),
        enabled=enabled,
    )
    db.add(mb)
    db.commit()
    return RedirectResponse("/mailboxes", status_code=303)


@router.post("/{mailbox_id}/toggle")
def toggle_mailbox(mailbox_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mb = _get(db, mailbox_id, effective_tenant_id(request, user))
    mb.enabled = not mb.enabled
    db.commit()
    return RedirectResponse("/mailboxes", status_code=303)


@router.post("/{mailbox_id}/poll")
def poll_now(
    mailbox_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mb = _get(db, mailbox_id, effective_tenant_id(request, user))
    label = mb.label
    started = poll_in_background(mb.id)
    if started:
        request.session["flash"] = {
            "kind": "ok",
            "text": (f"{label}: Prüfung läuft im Hintergrund. "
                     "Aktualisiere die Seite in 30 s — Ergebnis erscheint in der Tabelle."),
        }
    else:
        request.session["flash"] = {
            "kind": "warn",
            "text": f"{label}: Prüfung läuft bereits — bitte warten.",
        }
    return RedirectResponse("/mailboxes", status_code=303)


@router.post("/{mailbox_id}/rescan")
def rescan_now(
    mailbox_id: int,
    request: Request,
    days: int = Form(90),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    mb = _get(db, mailbox_id, effective_tenant_id(request, user))
    label = mb.label
    days = max(1, min(365, days))
    started = poll_in_background(mb.id, rescan=True, rescan_days=days)
    if started:
        request.session["flash"] = {
            "kind": "ok",
            "text": (f"{label}: Bestand der letzten {days} Tage wird neu eingelesen "
                     "(unabhängig vom Gelesen-Status). Läuft im Hintergrund — "
                     "Aktualisiere die Seite in ein bis zwei Minuten."),
        }
    else:
        request.session["flash"] = {
            "kind": "warn",
            "text": f"{label}: Es läuft bereits eine Prüfung — bitte warten.",
        }
    return RedirectResponse("/mailboxes", status_code=303)


@router.post("/{mailbox_id}/delete")
def delete_mailbox(mailbox_id: int, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    mb = _get(db, mailbox_id, effective_tenant_id(request, user))
    db.delete(mb)
    db.commit()
    return RedirectResponse("/mailboxes", status_code=303)
