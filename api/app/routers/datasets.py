from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Dataset, User
from ..schemas import DatasetCreate, DatasetOut

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.query(Dataset).order_by(Dataset.created_at.desc()).all()


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(
    body: DatasetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dataset = Dataset(name=body.name, created_by=user.id)
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="数据集不存在")
    db.delete(dataset)
    db.commit()
    return {"ok": True}
