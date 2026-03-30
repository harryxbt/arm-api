from fastapi import APIRouter, Depends, HTTPException, Response, Cookie, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import SignupRequest, LoginRequest, TokenResponse, UserResponse
from app.schemas.clipper import ClipperLoginRequest, ClipperTokenResponse
from app.services.auth import (
    hash_password,
    verify_password,
    create_access_token,
    create_clipper_access_token,
    create_refresh_token,
    rotate_refresh_token,
)
from app.services.stripe_service import create_customer

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
    )
    try:
        stripe_id = create_customer(body.email)
        user.stripe_customer_id = stripe_id
    except Exception:
        pass  # don't block signup if Stripe is unavailable locally
    db.add(user)
    db.commit()
    db.refresh(user)
    access_token = create_access_token(subject=str(user.id))
    refresh = create_refresh_token(db, user.id)
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(subject=str(user.id))
    refresh = create_refresh_token(db, user.id)
    response.set_cookie("refresh_token", refresh, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(response: Response, refresh_token: str = Cookie(None), db: Session = Depends(get_db)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")
    result = rotate_refresh_token(db, refresh_token)
    if not result:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    new_token, user_id = result
    access_token = create_access_token(subject=str(user_id))
    response.set_cookie("refresh_token", new_token, httponly=True, samesite="lax", max_age=30 * 24 * 3600)
    return TokenResponse(access_token=access_token)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(user.id),
        email=user.email,
        credits_remaining=user.credits_remaining,
        is_active=user.is_active,
    )


@router.post("/clipper/login", response_model=ClipperTokenResponse)
def clipper_login(body: ClipperLoginRequest, db: Session = Depends(get_db)):
    from app.models.clipper import Clipper
    clipper = db.query(Clipper).filter(Clipper.email == body.email).first()
    if not clipper or not verify_password(body.password, clipper.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not clipper.is_active:
        raise HTTPException(status_code=401, detail="Account deactivated")
    token = create_clipper_access_token(clipper.id, clipper.name)
    return ClipperTokenResponse(access_token=token, name=clipper.name)
