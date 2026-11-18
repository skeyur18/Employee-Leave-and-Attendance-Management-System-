# Employee Leave and Attendance Management System (ELAMS)

A complete web application for managing employee attendance and leave, with a login system,
role-based access (Employee / Manager), a database, a REST API and a colourful responsive website.

**Team 12**

| Roll Number |
|-------------|
| 2410030152 |
| 2410030168 |
| 2410030370 |
| 2410030364 |
| 2410030361 |

## Features

**Everyone**
- Secure sign-in (salted PBKDF2 password hashing, HttpOnly session cookie, 12-hour sessions)
- One-tap daily check-in / check-out with live clock; hours are calculated automatically
- Attendance history by month, weekly hours chart, leave balance
- Apply for leave (Casual, Sick, Earned, Unpaid) with validation: date order, balance, 30-day limit, overlapping requests
- Track request status and manager comments; change password
- Five switchable colour themes and a public landing page

**Managers**
- Dashboard with team numbers: active employees, present today, on leave today, pending approvals
- Approve or reject leave with a comment (approved leave is deducted from the balance; managers cannot review their own requests)
- Add employees, change roles, set leave balance, activate / deactivate accounts
- View everyone's attendance
- Monthly report (days present, hours, attendance %, leave days) with **CSV download**

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.8+, standard library only (`http.server`, `sqlite3`, `hashlib`) |
| Database | SQLite (file `elams.db`, created automatically) |
| Frontend | HTML, CSS, vanilla JavaScript (served by the same server) |
| Tests | `unittest` (23 tests: business logic and the HTTP API) |

No packages to install.

## Project structure

```
.
├── server.py              # Web server: REST API + serves the website
├── elams/
│   ├── db.py              # SQLite schema and connection
│   ├── auth.py            # Password hashing, login, sessions
│   └── services.py        # Employees, attendance, leave, dashboard, reports, demo data
├── static/
│   ├── index.html         # Landing page, login, application screens
│   ├── style.css          # Styles and colour themes
│   └── app.js             # Front-end logic (calls the API)
├── tests/
│   ├── test_services.py
│   └── test_api.py
├── render.yaml            # One-click hosting on Render
├── requirements.txt
└── README.md
```

## Run locally

```bash
python server.py
```

Open **http://127.0.0.1:8000**. On first start the database is filled with demo data.

### Demo accounts

| Role | Email | Password |
|------|-------|----------|
| Manager | ravi@company.com | manager123 |
| Manager | priya@company.com | manager123 |
| Employee | asha@company.com | employee123 |
| Employee | vineeth@company.com | employee123 |
| Employee | sneha@company.com | employee123 |
| Employee | karthik@company.com | employee123 |

## Run the tests

```bash
python -m unittest discover -s tests
```

## Host it online (free)

GitHub Pages can only host static files, so it cannot run the Python backend.
Use **Render** (free) and connect it to this GitHub repository:

1. Push this project to GitHub (see below).
2. Sign in at https://render.com with your GitHub account.
3. Choose **New → Blueprint** and select this repository (it reads `render.yaml`).
   If you use **New → Web Service** instead: Runtime **Python**, Build Command `echo ok`, Start Command `python server.py`, Plan **Free**.
4. Click **Deploy**. After a minute Render gives you a public link such as `https://your-app.onrender.com`.

Notes: the server reads the `PORT` environment variable automatically. On Render's free plan the
database file is reset when the service restarts, and the demo data is created again automatically.
For permanent data, attach a persistent disk and set `ELAMS_DB` to a path on it.

## Upload to GitHub

```bash
git init
git add .
git commit -m "Employee Leave and Attendance Management System"
git branch -M main
git remote add origin https://github.com/2410030364-vineeth/Employee-Leave-and-Attendance-Management-System.git
git push -u origin main
```

## API overview

| Method | Endpoint | Access |
|--------|----------|--------|
| POST | `/api/login`, `/api/logout` | public |
| GET | `/api/me`, `/api/dashboard`, `/api/meta` | signed in |
| POST | `/api/checkin`, `/api/checkout`, `/api/password` | signed in |
| GET | `/api/attendance?month=YYYY-MM[&scope=all]` | signed in (`scope=all`: manager) |
| GET / POST | `/api/leaves` (`?scope=mine`, `pending`, `all`) | signed in (`pending`/`all`: manager) |
| POST | `/api/leaves/<id>/approve`, `/api/leaves/<id>/reject` | manager |
| GET / POST / PUT | `/api/employees`, `/api/employees/<id>` | manager |
| GET | `/api/report?month=YYYY-MM`, `/api/report.csv?month=YYYY-MM` | manager |

All changing requests need the header `X-Requested-With: fetch` (basic CSRF protection).

## Security notes

- Passwords are never stored in plain text (salted PBKDF2-SHA256, 120,000 iterations).
- Session tokens are random, stored hashed, and sent in an HttpOnly, SameSite=Lax cookie (plus `Secure` behind HTTPS).
- All database queries are parameterised; all user text is escaped before it is shown in the page.
- Change the demo passwords before using the system with real data.
