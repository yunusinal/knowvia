from pydantic import BaseModel, ConfigDict

from app.db.models import Department, Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """API'nin dışarıya gösterdiği kullanıcı bilgisi; password_hash bilerek yok."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: Role
    department: Department | None
