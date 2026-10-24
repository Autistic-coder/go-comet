from __future__ import annotations

import os
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, HTTPException, Request, Response, status

from .database import connection
from .security import random_token, token_hash


SESSION_COOKIE = "gocomet_session"
CSRF_COOKIE = "gocomet_csrf"
SESSION_HOURS = 8


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class UserContext:
    id: int
    email: str
    display_name: str
    role: str
    supplier_name: str | None
    carrier_name: str | None
    tenant_id: str
    csrf_hash: str

    def public(self) -> dict:
        return {
            "id": self.id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "supplier_name": self.supplier_name,
            "carrier_name": self.carrier_name,
            "tenant_id": self.tenant_id,
        }


def create_session(user_id: int) -> tuple[str, str]:
    session_token = random_token()
    csrf_token = random_token()
    now = _utc_now()
    with connection() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
        db.execute(
            """INSERT INTO sessions (
                user_id, token_hash, csrf_hash, expires_at, created_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                token_hash(session_token),
                token_hash(csrf_token),
                (now + timedelta(hours=SESSION_HOURS)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
    return session_token, csrf_token


def set_auth_cookies(response: Response, session_token: str, csrf_token: str) -> None:
    max_age = SESSION_HOURS * 60 * 60
    common = {
        "max_age": max_age,
        "secure": _cookie_secure(),
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, session_token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **common)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=_cookie_secure(), samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=_cookie_secure(), samesite="strict")


def current_user(request: Request) -> UserContext:
    raw_token = request.cookies.get(SESSION_COOKIE)
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    now = _utc_now()
    with connection() as db:
        row = db.execute(
            """SELECT
                u.id, u.email, u.display_name, u.role, u.supplier_name, u.carrier_name,
                u.tenant_id,
                u.is_active, s.id AS session_id, s.csrf_hash, s.expires_at, s.last_seen_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?""",
            (token_hash(raw_token),),
        ).fetchone()
        if not row or not row["is_active"] or _parse(row["expires_at"]) <= now:
            if row:
                db.execute("DELETE FROM sessions WHERE id = ?", (row["session_id"],))
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid or expired")
        if _parse(row["last_seen_at"]) < now - timedelta(minutes=5):
            db.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE id = ?",
                (now.isoformat(), row["session_id"]),
            )

    return UserContext(
        id=row["id"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        supplier_name=row["supplier_name"],
        carrier_name=row["carrier_name"],
        tenant_id=row["tenant_id"],
        csrf_hash=row["csrf_hash"],
    )


def require_role(role: str) -> Callable:
    def dependency(user: UserContext = Depends(current_user)) -> UserContext:
        if user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {role} role",
            )
        return user

    return dependency


def require_csrf(request: Request, user: UserContext = Depends(current_user)) -> UserContext:
    header_token = request.headers.get("X-CSRF-Token", "")
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if (
        not header_token
        or not cookie_token
        or header_token != cookie_token
        or token_hash(header_token) != user.csrf_hash
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return user


class SlidingWindowLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window = timedelta(seconds=window_seconds)
        self._events: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = _utc_now()
        cutoff = now - self.window
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many attempts. Try again later.",
                    headers={"Retry-After": str(int(self.window.total_seconds()))},
                )
            events.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)
