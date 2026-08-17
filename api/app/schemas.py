from typing import Any, Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    role: str
    disabled: bool

    class Config:
        from_attributes = True


class TaskCreate(BaseModel):
    kind: str
    session_id: Optional[str] = None
    config: dict[str, Any] = {}


class TaskOut(BaseModel):
    id: str
    session_id: Optional[str]
    parent_task_id: Optional[str]
    kind: str
    status: str
    config: dict[str, Any]
    result: dict[str, Any]
    report_id: Optional[str]
    created_at: Any
    updated_at: Any

    class Config:
        from_attributes = True


class ProfileCreate(BaseModel):
    name: str
    protocol: str
    base_url: str
    model: str
    api_key: Optional[str] = None


class ProfileOut(BaseModel):
    id: str
    name: str
    protocol: str
    base_url: str
    model: str
    created_at: Any

    class Config:
        from_attributes = True


class DatasetCreate(BaseModel):
    name: str


class DatasetOut(BaseModel):
    id: str
    name: str
    version: int
    row_count: int
    created_at: Any

    class Config:
        from_attributes = True


class SettingsOut(BaseModel):
    key: str
    value: dict[str, Any]

    class Config:
        from_attributes = True
