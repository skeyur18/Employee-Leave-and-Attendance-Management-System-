import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

ITERATIONS = 120_000
SESSION_HOURS = 12


class AuthError(Exception):
    """Raised when sign-in fails or a session is missing/expired."""


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return salt.hex() + "$" + dk.hex()


def verify_password(password, stored):
    try:
        salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), ITERATIONS)
    except ValueError:
        return False
    return hmac.compare_digest(dk.hex(), dk_hex)


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(conn, email, password):
    row = conn.execute(
        "SELECT * FROM employees WHERE email=? AND active=1", ((email or "").strip().lower(),)
    ).fetchone()
    if row is None or not verify_password(password or "", row["password_hash"]):
        raise AuthError("Incorrect email or password.")
    cutoff = (datetime.now() - timedelta(hours=SESSION_HOURS)).isoformat()
    conn.execute("DELETE FROM sessions WHERE created < ?", (cutoff,))
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (token_hash, employee_id, created) VALUES (?,?,?)",
        (_h(token), row["id"], datetime.now().isoformat()),
    )
    conn.commit()
    return token, row


def user_for_token(conn, token):
    row = conn.execute(
        """SELECT e.*, s.created AS s_created FROM sessions s
           JOIN employees e ON e.id = s.employee_id
           WHERE s.token_hash=? AND e.active=1""",
        (_h(token),),
    ).fetchone()
    if row is None:
        return None
    if datetime.now() - datetime.fromisoformat(row["s_created"]) > timedelta(hours=SESSION_HOURS):
        logout(conn, token)
        return None
    return row


def logout(conn, token):
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_h(token),))
    conn.commit()
