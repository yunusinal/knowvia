from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import DUMMY_PASSWORD_HASH, create_access_token, verify_password
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    """E-posta (form alanı: username) ve parolayla giriş; başarılıysa JWT döner."""
    user = db.scalars(select(User).where(User.email == form.username)).first()

    if user is None:
        verify_password(form.password, DUMMY_PASSWORD_HASH)
        password_ok = False
    else:
        password_ok = verify_password(form.password, user.password_hash)

    # Var olmayan e-posta, yanlış parola ve pasif hesap aynı cevabı alır.
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-posta veya parola hatalı.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me")
def me(current_user: Annotated[User, Depends(get_current_user)]) -> UserOut:
    return UserOut.model_validate(current_user)
