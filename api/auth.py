from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import bcrypt
from fastapi import Depends, Header, HTTPException

IDLE_MINUTES = 30
RESET_TOKEN_MINUTES = 15

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "project_manager": ["view_stats", "view_alerts", "view_users", "view_reports"],
    "hse": ["view_stats", "view_alerts", "check_image", "view_reports"],
    "site_engineer": ["view_stats", "view_alerts", "check_image"],
    "hr_manager": ["view_stats", "view_users"],
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    role          TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT    NOT NULL,
    last_active TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS password_resets (
    token      TEXT    PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT    NOT NULL
);
"""


def now() -> datetime:
    return datetime.now()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))


def user_payload(row: sqlite3.Row) -> dict:
    return {"name": row["name"], "email": row["email"], "role": row["role"],
            "permissions": ROLE_PERMISSIONS.get(row["role"], [])}


class Auth:

    def __init__(self, connect: Callable[[], sqlite3.Connection], seed_file: Path):
        self.connect = connect
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            if seed_file.exists():
                self._sync_users(conn, seed_file)

    def _sync_users(self, conn: sqlite3.Connection, seed_file: Path) -> None:
        users = json.loads(seed_file.read_text(encoding="utf-8"))
        wanted = {}
        for u in users:
            if u["role"] not in ROLE_PERMISSIONS:
                raise ValueError(f"{seed_file.name}: unknown role {u['role']!r} for {u['email']}")
            wanted[u["email"].strip().lower()] = u

        existing = {r["email"]: r for r in conn.execute("SELECT * FROM users")}
        added = updated = removed = 0
        for email, u in wanted.items():
            row = existing.get(email)
            if row is None:
                conn.execute(
                    "INSERT INTO users (email, name, role, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (email, u["name"], u["role"], hash_password(u["password"]), now().isoformat(timespec="seconds")),
                )
                added += 1
                continue
            same_password = check_password(u["password"], row["password_hash"])
            if row["name"] != u["name"] or row["role"] != u["role"] or not same_password:
                conn.execute("UPDATE users SET name = ?, role = ?, password_hash = ? WHERE id = ?",
                             (u["name"], u["role"],
                              row["password_hash"] if same_password else hash_password(u["password"]), row["id"]))
                if not same_password or row["role"] != u["role"]:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
                updated += 1
        for email, row in existing.items():
            if email not in wanted:
                conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["id"],))
                conn.execute("DELETE FROM password_resets WHERE user_id = ?", (row["id"],))
                conn.execute("DELETE FROM users WHERE id = ?", (row["id"],))
                removed += 1
        if added or updated or removed:
            print(f"Users synced from {seed_file.name}: {added} added, {updated} updated, {removed} removed")

    def login(self, email: str, password: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if row is None or not check_password(password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="Wrong email or password")
            token = secrets.token_urlsafe(32)
            stamp = now().isoformat(timespec="seconds")
            conn.execute("INSERT INTO sessions (token, user_id, created_at, last_active) VALUES (?, ?, ?, ?)",
                         (token, row["id"], stamp, stamp))
        return {"token": token, "user": user_payload(row)}

    def logout(self, token: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def user_for_token(self, token: str) -> sqlite3.Row:
        cutoff = (now() - timedelta(minutes=IDLE_MINUTES)).isoformat(timespec="seconds")
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE last_active < ?", (cutoff,))
            row = conn.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE token = ?",
                (token,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=401, detail="Not signed in or session expired")
            conn.execute("UPDATE sessions SET last_active = ? WHERE token = ?",
                         (now().isoformat(timespec="seconds"), token))
        return row

    def create_reset_token(self, email: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
            if row is None:
                return None
            token = secrets.token_urlsafe(32)
            expires = (now() + timedelta(minutes=RESET_TOKEN_MINUTES)).isoformat(timespec="seconds")
            conn.execute("INSERT INTO password_resets (token, user_id, expires_at) VALUES (?, ?, ?)",
                         (token, row["id"], expires))
        return token

    def reset_password(self, token: str, new_password: str) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT user_id, expires_at FROM password_resets WHERE token = ?", (token,)).fetchone()
            if row is None or row["expires_at"] < now().isoformat(timespec="seconds"):
                raise HTTPException(status_code=400, detail="Reset link is invalid or expired")
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), row["user_id"]))
            conn.execute("DELETE FROM password_resets WHERE user_id = ?", (row["user_id"],))
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))

    def list_users(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [{"name": r["name"], "email": r["email"], "role": r["role"]} for r in rows]

    def current_user(self) -> Callable:
        def dependency(authorization: str = Header(default="")) -> sqlite3.Row:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise HTTPException(status_code=401, detail="Not signed in")
            return self.user_for_token(token)
        return dependency

    def require(self, permission: str) -> Callable:
        current = self.current_user()

        def dependency(user: sqlite3.Row = Depends(current)) -> sqlite3.Row:
            if permission not in ROLE_PERMISSIONS.get(user["role"], []):
                raise HTTPException(status_code=403, detail=f"Your role cannot {permission}")
            return user
        return dependency
