from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_admin
from ..errors import AppError, ErrorCode
from ..models import AuditLog, ProtocolProfile, User
from ..schemas import ProfileCreate, ProfileOut
from ..security import encrypt_secret

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("", response_model=list[ProfileOut])
def list_profiles(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(ProtocolProfile).order_by(ProtocolProfile.created_at.desc()).all()


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(
    body: ProfileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    profile = ProtocolProfile(
        name=body.name,
        protocol=body.protocol,
        base_url=body.base_url,
        model=body.model,
        encrypted_key=encrypt_secret(body.api_key) if body.api_key else None,
        created_by=user.id,
    )
    db.add(profile)
    db.add(AuditLog(action="profile_create", detail={"name": body.name, "by": user.id}))
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    profile = db.query(ProtocolProfile).filter(ProtocolProfile.id == profile_id).first()
    if not profile:
        raise AppError(ErrorCode.NOT_FOUND, "协议档不存在")
    db.delete(profile)
    db.add(AuditLog(action="profile_delete", detail={"name": profile.name, "by": user.id}))
    db.commit()
    return {"ok": True}
