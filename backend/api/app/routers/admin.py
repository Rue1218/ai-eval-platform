from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import Setting, User

router = APIRouter(prefix="/api/admin", tags=["admin"])

DEFAULT_SETTINGS = {
    "max_running_tasks": 3,
    "max_inflight_model_calls": 8,
    "default_task_budget_usd": 5,
    "stress_default_qps": 100,
    "stress_max_duration_s": 1800,
}


def _load(db: Session) -> dict[str, Any]:
    merged = dict(DEFAULT_SETTINGS)
    for row in db.query(Setting).all():
        merged[row.key] = row.value
    return merged


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _load(db)


@router.put("/settings")
def put_settings(
    body: dict[str, Any],
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    for key, value in body.items():
        row = db.query(Setting).filter(Setting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    return _load(db)
