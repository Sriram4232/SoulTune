"""Profile updates, password changes, and account deletion routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ...core.models import AccountDelete, PasswordChange, ProfileUpdate
from ...core.security import hash_password, verify_password
from ..dependencies import (
    API, AUTH_ERROR, authenticated, issue_session, public_user, rate,
)

router = APIRouter(tags=["account"])


@router.put(f"{API}/profile")
def update_profile(body: ProfileUpdate, request: Request, auth: tuple = Depends(authenticated)):
    user, session = auth
    user = request.app.state.store.update_profile(user["id"], body.model_dump(exclude_none=True))
    if not user:
        raise HTTPException(401, "Please sign in to continue.")
    return {"user": public_user(user), "csrf_token": session["csrf_token"]}


@router.post(f"{API}/auth/change-password")
def change_password(body: PasswordChange, request: Request, response: Response, auth: tuple = Depends(authenticated)):
    user, _ = auth
    if user["is_guest"]:
        raise HTTPException(400, "Create an account to set a password.")
    rate(request, "password-change", 10, 900, user["id"])
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(401, AUTH_ERROR)
    user = request.app.state.store.rotate_password(user["id"], hash_password(body.new_password), user.get("auth_version", 0))
    if not user:
        raise HTTPException(409, "Your credentials changed. Please sign in again.")
    return issue_session(request, response, user)


@router.delete(f"{API}/account")
def delete_account(body: AccountDelete, request: Request, response: Response, auth: tuple = Depends(authenticated)):
    config = request.app.state.settings
    user, _ = auth
    rate(request, "account-delete", 10, 900, user["id"])
    if not user["is_guest"] and not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, AUTH_ERROR)
    request.app.state.store.delete_user(user["id"])
    response.delete_cookie(config.cookie_name, path="/", secure=config.cookie_secure,
                           httponly=True, samesite=config.cookie_samesite)
    return {"message": "Your account and playlists have been deleted."}
