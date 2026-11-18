"""ELAMS web server: JSON API + static website. Standard library only.

Run:  python server.py        then open http://127.0.0.1:8000
"""
import json
import mimetypes
import os
import re
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from elams import auth, services
from elams.db import get_conn

STATIC = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"))
ROUTES = []


class Raw:
    """A non-JSON response (used for CSV download)."""
    def __init__(self, body, ctype, filename=None):
        self.body, self.ctype, self.filename = body.encode(), ctype, filename


class Ctx:
    def __init__(self, conn, user, body, query, match, token, secure):
        self.conn, self.user, self.body, self.query = conn, user, body, query
        self.match, self.token, self.secure = match, token, secure
        self.cookies = []

    def set_session(self, token, clear=False):
        c = f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={0 if clear else auth.SESSION_HOURS * 3600}"
        self.cookies.append(c + ("; Secure" if self.secure else ""))

    def arg(self, name, default=None):
        return self.query.get(name, [default])[0]


def route(method, pattern, access="user"):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), access, fn))
        return fn
    return deco


# ------------------------------------------------------------------- auth
@route("POST", "/api/login", None)
def login(c):
    token, user = auth.login(c.conn, c.body.get("email"), c.body.get("password"))
    c.set_session(token)
    return {"user": services.public(user)}


@route("POST", "/api/logout", None)
def logout(c):
    if c.token:
        auth.logout(c.conn, c.token)
    c.set_session("", clear=True)
    return {"ok": True}


@route("GET", "/api/me")
def me(c):
    return {"user": services.public(c.user)}


@route("POST", "/api/password")
def password(c):
    services.change_password(c.conn, c.user["id"], c.body.get("old"), c.body.get("new"))
    return {"ok": True}


@route("GET", "/api/meta")
def meta(c):
    return {"leave_types": services.LEAVE_TYPES}


# -------------------------------------------------------------- dashboard
@route("GET", "/api/dashboard")
def dashboard(c):
    return services.dashboard(c.conn, c.user)


# ------------------------------------------------------------- attendance
@route("POST", "/api/checkin")
def checkin(c):
    day, time = services.check_in(c.conn, c.user["id"])
    return {"date": day, "time": time}


@route("POST", "/api/checkout")
def checkout(c):
    day, time = services.check_out(c.conn, c.user["id"])
    return {"date": day, "time": time}


@route("GET", "/api/attendance")
def attendance(c):
    everyone = c.arg("scope") == "all"
    if everyone and c.user["role"] != "manager":
        raise PermissionError("Only managers can view everyone’s attendance.")
    rows = services.list_attendance(c.conn, None if everyone else c.user["id"], c.arg("month"),
                                    c.arg("limit"))
    return {"attendance": rows}


# ------------------------------------------------------------------ leave
@route("POST", "/api/leaves")
def apply(c):
    b = c.body
    lid = services.apply_leave(c.conn, c.user["id"], b.get("type"), b.get("start"), b.get("end"), b.get("reason"))
    return 201, {"id": lid}


@route("GET", "/api/leaves")
def leaves(c):
    scope = c.arg("scope", "mine")
    if scope in ("pending", "all") and c.user["role"] != "manager":
        raise PermissionError("Only managers can view other people’s requests.")
    return {"leaves": services.list_leaves(c.conn, scope, c.user["id"])}


@route("POST", r"/api/leaves/(\d+)/(approve|reject)")
def decide(c):
    services.decide_leave(c.conn, c.user["id"], int(c.match.group(1)),
                          c.match.group(2) == "approve", c.body.get("comment", ""))
    return {"ok": True}


# -------------------------------------------------------------- employees
@route("GET", "/api/employees", "manager")
def employees(c):
    return {"employees": services.list_employees(c.conn)}


@route("POST", "/api/employees", "manager")
def add_employee(c):
    b = c.body
    emp_id = services.add_employee(c.conn, b.get("name"), b.get("email"), b.get("password"),
                                   b.get("department"), b.get("designation"), b.get("role", "employee"),
                                   b.get("leave_balance", 20))
    return 201, {"id": emp_id}


@route("PUT", r"/api/employees/(\d+)", "manager")
def update_employee(c):
    services.update_employee(c.conn, c.user["id"], int(c.match.group(1)), c.body)
    return {"ok": True}


# ---------------------------------------------------------------- reports
@route("GET", "/api/report", "manager")
def report(c):
    return services.monthly_report(c.conn, c.arg("month", ""))


@route("GET", "/api/report.csv", "manager")
def report_csv(c):
    month = c.arg("month", "")
    return Raw(services.report_csv(services.monthly_report(c.conn, month)), "text/csv; charset=utf-8",
               f"attendance-report-{month}.csv")


# ----------------------------------------------------------------- server
class Handler(BaseHTTPRequestHandler):
    server_version = "ELAMS/1.0"

    def _send(self, status, body, ctype, headers=()):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api") else "no-cache")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj, cookies=()):
        self._send(status, json.dumps(obj).encode(), "application/json",
                   [("Set-Cookie", c) for c in cookies])

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            raise ValueError("Request is too large.")
        if n == 0:
            return {}
        try:
            data = json.loads(self.rfile.read(n))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("Request body must be valid JSON.")
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object.")
        return data

    def _dispatch(self, method):
        url = urlparse(self.path)
        if url.path.startswith("/api/"):
            return self._api(method, url.path, parse_qs(url.query))
        if method != "GET":
            return self._json(405, {"error": "Method not allowed."})
        return self._static(url.path)

    def _api(self, method, path, query):
        for m, rx, access, fn in ROUTES:
            match = rx.match(path)
            if match and m == method:
                break
        else:
            return self._json(404, {"error": "Not found."})
        conn = get_conn()
        try:
            if method != "GET" and self.headers.get("X-Requested-With") != "fetch":
                return self._json(400, {"error": "Missing X-Requested-With header."})
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            token = cookie["session"].value if "session" in cookie else None
            user = auth.user_for_token(conn, token) if token else None
            if access and user is None:
                return self._json(401, {"error": "Please sign in."})
            if access == "manager" and user["role"] != "manager":
                return self._json(403, {"error": "Managers only."})
            secure = self.headers.get("X-Forwarded-Proto") == "https"
            ctx = Ctx(conn, user, self._body() if method in ("POST", "PUT") else {}, query, match, token, secure)
            result = fn(ctx)
            if isinstance(result, Raw):
                hdrs = [("Content-Disposition", f'attachment; filename="{result.filename}"')] if result.filename else []
                return self._send(200, result.body, result.ctype, hdrs)
            status, obj = result if isinstance(result, tuple) else (200, result)
            return self._json(status, obj, ctx.cookies)
        except auth.AuthError as e:
            self._json(401, {"error": str(e)})
        except PermissionError as e:
            self._json(403, {"error": str(e)})
        except LookupError as e:
            self._json(404, {"error": str(e)})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "Something went wrong on the server."})
        finally:
            conn.close()

    def _static(self, path):
        full = os.path.realpath(os.path.join(STATIC, ("index.html" if path in ("", "/") else path.lstrip("/"))))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, b"Page not found", "text/plain; charset=utf-8")
        with open(full, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        self._send(200, body, ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))

    def do_GET(self): self._dispatch("GET")
    def do_POST(self): self._dispatch("POST")
    def do_PUT(self): self._dispatch("PUT")

    def log_message(self, fmt, *args):
        if os.environ.get("ELAMS_QUIET") != "1":
            super().log_message(fmt, *args)


def make_server(host="127.0.0.1", port=8000):
    return ThreadingHTTPServer((host, port), Handler)


if __name__ == "__main__":
    conn = get_conn()
    if os.environ.get("ELAMS_SEED", "1") == "1" and services.seed_demo(conn):
        print("Demo data created (see README for demo logins).")
    conn.close()
    port = int(os.environ.get("PORT", 8000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    print(f"ELAMS running on http://{host}:{port}  (Ctrl+C to stop)")
    try:
        make_server(host, port).serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
