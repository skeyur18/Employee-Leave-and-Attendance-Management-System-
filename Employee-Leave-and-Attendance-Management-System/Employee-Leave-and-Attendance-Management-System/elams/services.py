"""Business logic: employees, attendance, leave, dashboard and reports."""
import csv
import io
import re
from datetime import date, datetime, timedelta
from sqlite3 import IntegrityError

from . import auth

LEAVE_TYPES = ("Casual", "Sick", "Earned", "Unpaid")
ROLES = ("employee", "manager")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def public(row):
    d = dict(row)
    d.pop("password_hash", None)
    d.pop("s_created", None)
    return d


# ------------------------------------------------------------------ employees
def get_employee(conn, emp_id):
    row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if row is None:
        raise LookupError("Employee not found.")
    return row


def add_employee(conn, name, email, password, department, designation="Staff",
                 role="employee", leave_balance=20):
    name, email = (name or "").strip(), (email or "").strip().lower()
    department, designation = (department or "").strip(), (designation or "").strip() or "Staff"
    if not name or not department:
        raise ValueError("Name and department are required.")
    if not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters.")
    if role not in ROLES:
        raise ValueError("Role must be employee or manager.")
    try:
        leave_balance = int(leave_balance)
    except (TypeError, ValueError):
        raise ValueError("Leave balance must be a number.")
    if not 0 <= leave_balance <= 365:
        raise ValueError("Leave balance must be between 0 and 365.")
    try:
        cur = conn.execute(
            """INSERT INTO employees
               (name,email,password_hash,department,designation,role,leave_balance,joined)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, email, auth.hash_password(password), department, designation, role,
             leave_balance, date.today().isoformat()),
        )
    except IntegrityError:
        raise ValueError("That email is already registered.")
    conn.commit()
    return cur.lastrowid


def update_employee(conn, actor_id, emp_id, data):
    get_employee(conn, emp_id)
    allowed = {"department", "designation", "role", "leave_balance", "active"}
    sets, vals = [], []
    for key, val in data.items():
        if key not in allowed:
            continue
        if key in ("role", "active") and emp_id == actor_id:
            raise ValueError("You can’t change your own role or status.")
        if key == "role" and val not in ROLES:
            raise ValueError("Role must be employee or manager.")
        if key == "active":
            val = 1 if val else 0
        if key == "leave_balance":
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise ValueError("Leave balance must be a number.")
            if not 0 <= val <= 365:
                raise ValueError("Leave balance must be between 0 and 365.")
        sets.append(f"{key}=?")  # key comes from the whitelist above
        vals.append(val)
    if not sets:
        raise ValueError("Nothing to update.")
    conn.execute(f"UPDATE employees SET {', '.join(sets)} WHERE id=?", (*vals, emp_id))
    if "active" in data and not data["active"]:
        conn.execute("DELETE FROM sessions WHERE employee_id=?", (emp_id,))
    conn.commit()


def list_employees(conn):
    return [public(r) for r in conn.execute("SELECT * FROM employees ORDER BY active DESC, name")]


def change_password(conn, emp_id, old, new):
    emp = get_employee(conn, emp_id)
    if not auth.verify_password(old or "", emp["password_hash"]):
        raise ValueError("Your current password is incorrect.")
    if len(new or "") < 6:
        raise ValueError("New password must be at least 6 characters.")
    conn.execute("UPDATE employees SET password_hash=? WHERE id=?", (auth.hash_password(new), emp_id))
    conn.commit()


# ----------------------------------------------------------------- attendance
def _hours(cin, cout):
    if not cout:
        return 0.0
    a, b = datetime.strptime(cin, "%H:%M:%S"), datetime.strptime(cout, "%H:%M:%S")
    return round(max((b - a).total_seconds(), 0) / 3600, 2)


def _att(row):
    d = dict(row)
    d["hours"] = _hours(d["check_in"], d["check_out"])
    return d


def check_in(conn, emp_id, now=None):
    emp = get_employee(conn, emp_id)
    if not emp["active"]:
        raise PermissionError("This account is inactive.")
    now = now or datetime.now()
    day, time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    if conn.execute(
        "SELECT 1 FROM leaves WHERE employee_id=? AND status='APPROVED' AND start_date<=? AND end_date>=?",
        (emp_id, day, day),
    ).fetchone():
        raise ValueError("You are on approved leave today.")
    try:
        conn.execute("INSERT INTO attendance (employee_id,date,check_in) VALUES (?,?,?)", (emp_id, day, time))
    except IntegrityError:
        raise ValueError("You have already checked in today.")
    conn.commit()
    return day, time


def check_out(conn, emp_id, now=None):
    get_employee(conn, emp_id)
    now = now or datetime.now()
    day, time = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    row = conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?", (emp_id, day)).fetchone()
    if row is None:
        raise ValueError("You haven’t checked in today.")
    if row["check_out"]:
        raise ValueError("You have already checked out today.")
    conn.execute("UPDATE attendance SET check_out=? WHERE id=?", (time, row["id"]))
    conn.commit()
    return day, time


def list_attendance(conn, emp_id=None, month=None, limit=None):
    q = ("SELECT a.*, e.name, e.department FROM attendance a "
         "JOIN employees e ON e.id = a.employee_id WHERE 1=1")
    params = []
    if emp_id is not None:
        q += " AND a.employee_id=?"
        params.append(emp_id)
    if month:
        if not MONTH_RE.match(month):
            raise ValueError("Month must be in YYYY-MM format.")
        q += " AND a.date LIKE ?"
        params.append(month + "-%")
    q += " ORDER BY a.date DESC, e.name"
    if limit:
        q += " LIMIT ?"
        params.append(int(limit))
    return [_att(r) for r in conn.execute(q, params)]


def today_status(conn, emp_id, now=None):
    day = (now or datetime.now()).strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM attendance WHERE employee_id=? AND date=?", (emp_id, day)).fetchone()
    if row is None:
        return {"state": "not_in", "check_in": None, "check_out": None, "hours": 0}
    a = _att(row)
    return {"state": "done" if a["check_out"] else "in", "check_in": a["check_in"],
            "check_out": a["check_out"], "hours": a["hours"]}


# ---------------------------------------------------------------------- leave
def _parse(s):
    try:
        return datetime.strptime(s or "", "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("Dates must be in YYYY-MM-DD format.")


def apply_leave(conn, emp_id, leave_type, start, end, reason=""):
    emp = get_employee(conn, emp_id)
    if leave_type not in LEAVE_TYPES:
        raise ValueError("Choose a valid leave type.")
    s, e = _parse(start), _parse(end)
    if e < s:
        raise ValueError("The end date can’t be before the start date.")
    days = (e - s).days + 1
    if days > 30:
        raise ValueError("A single request can’t be longer than 30 days.")
    if leave_type != "Unpaid" and days > emp["leave_balance"]:
        raise ValueError(f"You asked for {days} day(s) but only have {emp['leave_balance']} left.")
    if conn.execute(
        """SELECT 1 FROM leaves WHERE employee_id=? AND status!='REJECTED'
           AND start_date<=? AND end_date>=?""", (emp_id, end, start)).fetchone():
        raise ValueError("These dates overlap with another leave request.")
    cur = conn.execute(
        "INSERT INTO leaves (employee_id,leave_type,start_date,end_date,days,reason) VALUES (?,?,?,?,?,?)",
        (emp_id, leave_type, start, end, days, (reason or "").strip()[:300]),
    )
    conn.commit()
    return cur.lastrowid


def decide_leave(conn, actor_id, leave_id, approve, comment=""):
    actor = get_employee(conn, actor_id)
    if actor["role"] != "manager":
        raise PermissionError("Only managers can review leave requests.")
    lv = conn.execute("SELECT * FROM leaves WHERE id=?", (leave_id,)).fetchone()
    if lv is None:
        raise LookupError("Leave request not found.")
    if lv["employee_id"] == actor_id:
        raise PermissionError("You can’t review your own leave request.")
    if lv["status"] != "PENDING":
        raise ValueError(f"This request was already {lv['status'].lower()}.")
    if approve and lv["leave_type"] != "Unpaid":
        emp = get_employee(conn, lv["employee_id"])
        if lv["days"] > emp["leave_balance"]:
            raise ValueError("The employee no longer has enough leave balance.")
        conn.execute("UPDATE employees SET leave_balance = leave_balance - ? WHERE id=?",
                     (lv["days"], emp["id"]))
    conn.execute(
        "UPDATE leaves SET status=?, decided_by=?, decided_on=?, comment=? WHERE id=?",
        ("APPROVED" if approve else "REJECTED", actor_id, datetime.now().isoformat(timespec="seconds"),
         (comment or "").strip()[:300], leave_id),
    )
    conn.commit()


def list_leaves(conn, scope="mine", emp_id=None):
    q = ("SELECT l.*, e.name, e.department, d.name AS decided_by_name FROM leaves l "
         "JOIN employees e ON e.id = l.employee_id LEFT JOIN employees d ON d.id = l.decided_by WHERE 1=1")
    params = []
    if scope == "mine":
        q += " AND l.employee_id=?"
        params.append(emp_id)
    elif scope == "pending":
        q += " AND l.status='PENDING' AND l.employee_id != ?"
        params.append(emp_id)
    return [dict(r) for r in conn.execute(q + " ORDER BY l.id DESC", params)]


# ------------------------------------------------------------ dashboard/report
def dashboard(conn, user, now=None):
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    uid = user["id"]
    one = lambda q, *p: conn.execute(q, p).fetchone()[0]
    data = {
        "today": today_status(conn, uid, now),
        "balance": user["leave_balance"],
        "present_month": one("SELECT COUNT(*) FROM attendance WHERE employee_id=? AND date LIKE ?", uid, day[:7] + "-%"),
        "pending_mine": one("SELECT COUNT(*) FROM leaves WHERE employee_id=? AND status='PENDING'", uid),
        "recent": list_attendance(conn, uid, limit=14),
    }
    if user["role"] == "manager":
        data["team"] = {
            "employees": one("SELECT COUNT(*) FROM employees WHERE active=1"),
            "present_today": one("SELECT COUNT(*) FROM attendance WHERE date=?", day),
            "on_leave_today": one("SELECT COUNT(*) FROM leaves WHERE status='APPROVED' AND start_date<=? AND end_date>=?", day, day),
            "pending_approvals": one("SELECT COUNT(*) FROM leaves WHERE status='PENDING' AND employee_id != ?", uid),
        }
    return data


def monthly_report(conn, month, today=None):
    if not MONTH_RE.match(month or ""):
        raise ValueError("Month must be in YYYY-MM format.")
    y, m = int(month[:4]), int(month[5:])
    first = date(y, m, 1)
    last = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    upto = min(last, today or date.today())
    working, d = 0, first
    while d <= upto:
        working += d.weekday() < 5
        d += timedelta(days=1)
    rows = []
    for emp in conn.execute("SELECT * FROM employees WHERE active=1 ORDER BY name").fetchall():
        atts = list_attendance(conn, emp["id"], month)
        leave_days = 0
        for lv in conn.execute("SELECT * FROM leaves WHERE employee_id=? AND status='APPROVED'", (emp["id"],)):
            a, b = max(_parse(lv["start_date"]), first), min(_parse(lv["end_date"]), last)
            leave_days += max((b - a).days + 1, 0)
        pending = conn.execute("SELECT COUNT(*) FROM leaves WHERE employee_id=? AND status='PENDING'",
                               (emp["id"],)).fetchone()[0]
        rows.append({
            "id": emp["id"], "name": emp["name"], "department": emp["department"],
            "present": len(atts), "hours": round(sum(a["hours"] for a in atts), 1),
            "attendance_pct": min(round(100 * len(atts) / working), 100) if working else 0,
            "leave_days": leave_days, "pending": pending,
        })
    return {"month": month, "working_days": working, "rows": rows}


def report_csv(report):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Employee", "Department", "Days present", "Hours worked",
                "Attendance %", "Approved leave days", "Pending requests"])
    for r in report["rows"]:
        w.writerow([r["name"], r["department"], r["present"], r["hours"],
                    r["attendance_pct"], r["leave_days"], r["pending"]])
    return out.getvalue()


# ----------------------------------------------------------------- demo data
def seed_demo(conn, today=None):
    """Fill an empty database with demo employees, attendance and leave requests."""
    if conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
        return False
    people = [
        ("Ravi Kumar", "ravi@company.com", "manager123", "HR", "HR Manager", "manager"),
        ("Priya Sharma", "priya@company.com", "manager123", "Operations", "Operations Head", "manager"),
        ("Asha Reddy", "asha@company.com", "employee123", "IT", "Software Engineer", "employee"),
        ("Vineeth", "vineeth@company.com", "employee123", "Development", "Full-stack Developer", "employee"),
        ("Sneha Rao", "sneha@company.com", "employee123", "Design", "UI Designer", "employee"),
        ("Karthik Varma", "karthik@company.com", "employee123", "Finance", "Accountant", "employee"),
    ]
    ids = [add_employee(conn, *p) for p in people]
    today = today or date.today()
    iso = lambda d: d.isoformat()
    leaves = [  # (employee index, type, start offset, end offset, reason, status)
        (2, "Casual", -12, -10, "Family function", "APPROVED"),
        (3, "Casual", 7, 9, "Trip to Goa", "PENDING"),
        (4, "Sick", 2, 2, "Medical appointment", "PENDING"),
        (5, "Earned", -20, -19, "Personal work", "REJECTED"),
    ]
    off = set()
    for i, typ, a, b, why, status in leaves:
        s, e = today + timedelta(days=a), today + timedelta(days=b)
        conn.execute(
            """INSERT INTO leaves (employee_id,leave_type,start_date,end_date,days,reason,status,decided_by,decided_on)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (ids[i], typ, iso(s), iso(e), b - a + 1, why, status,
             ids[0] if status != "PENDING" else None, datetime.now().isoformat(timespec="seconds") if status != "PENDING" else None))
        if status == "APPROVED":
            conn.execute("UPDATE employees SET leave_balance = leave_balance - ? WHERE id=?", (b - a + 1, ids[i]))
            off |= {(i, iso(s + timedelta(days=k))) for k in range(b - a + 1)}
    for back in range(1, 29):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        for i, emp_id in enumerate(ids):
            if (back + i) % 9 == 0 or (i, iso(day)) in off:
                continue
            cin = f"09:{5 + (back * 3 + i * 7) % 40:02d}:00"
            cout = f"{17 + (back + i) % 2}:{(back * 7 + i * 11) % 50 + 5:02d}:00"
            conn.execute("INSERT INTO attendance (employee_id,date,check_in,check_out) VALUES (?,?,?,?)",
                         (emp_id, iso(day), cin, cout))
    conn.commit()
    return True
