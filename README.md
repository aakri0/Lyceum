# Student ERP Management System

A full-stack Enterprise Resource Planning (ERP) platform for educational institutions. The system provides role-based portals for **students**, **faculty**, and **administrators** to manage academic records, course enrollment, grading, student welfare requests, and institutional analytics.

Built with **Flask**, **MySQL**, and **Jinja2**, with Chart.js-powered dashboards and OTP-secured email authentication.

---

## About

Most college workflows — checking grades, submitting a hostel request, updating a roster, promoting a cohort at the end of the semester — still happen through a patchwork of email threads, spreadsheets, and paper forms. This project consolidates those flows into a single, self-hostable web app that a small department can stand up on a laptop or a modest VPS.

**What it does**

- Gives students a live view of their CGPA, semester GPA, and grade history, plus a *what-if* simulator for planning.
- Lets faculty own their courses end-to-end: create a course, enroll students, record component-level marks (attendance, assignments, internals, externals), and process student-welfare requests routed to them.
- Gives administrators the levers to run the institution: create users, manage departments, promote cohorts in bulk, audit actions, and export request data as CSV — all filterable by date range.
- Secures access with email OTP login, bcrypt password hashing, forced reset on first login, CSRF-protected forms, rate-limited auth endpoints, and hardened session cookies.

**Who it's for**

- Small colleges and departments looking for a lightweight alternative to heavy commercial ERPs.
- Students of software engineering and databases who want a realistic Flask + MySQL codebase to read, extend, or fork.
- Developers evaluating role-based-access patterns, OTP flows, or Jinja dashboards as a reference.

**Design principles**

- **Boring stack, readable code.** One `app.py` holds every route so flow-through is easy to trace. Templates are plain Jinja — no build step.
- **Safe defaults.** Secrets live in env vars, sessions are HTTP-only, CSRF is global, auth endpoints are rate-limited, and DB connections are cleaned up in a teardown hook.
- **Zero vendor lock-in.** MySQL + SMTP + a WSGI server is all you need. Run it on bare metal, a VPS, or behind any reverse proxy.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Database Setup](#database-setup)
- [Running the Application](#running-the-application)
- [Docker](#docker)
- [Tests & CI](#tests--ci)
- [Operations](#operations)
- [Default Roles & Workflows](#default-roles--workflows)
- [Security Notes](#security-notes)
- [Contributing](#contributing)
- [License](#license)

---

## Features

### Student Portal
- Personal dashboard with **CGPA** and semester-wise **GPA** analytics
- View enrolled courses, credits, and grade breakdowns
- **Grade simulator** — run what-if scenarios against current grades
- Submit **Student Welfare Division (SWD)** requests (leave, bonafide, grievances, etc.)
- Track request status and faculty assignment
- Secure profile management and password reset

### Faculty Portal
- Course management (create, edit, assign credits and semesters)
- Student enrollment and roster management
- **Component-based grading** — attendance, assignments, internals, externals
- Review and process SWD requests forwarded by administration
- Per-course analytics and student progress insights

### Admin Portal
- User provisioning for students, faculty, and administrators
- **Bulk semester promotion** for cohorts
- Department CRUD and faculty/department assignments
- Institutional **analytics dashboard**:
  - Total students, faculty, and pending/resolved requests
  - Request distribution by category, status, and department
  - Date-range filtering
- **Audit log** for action tracking
- **CSV export** of SWD requests
- Request routing and faculty assignment

### Platform-wide
- **OTP-based login** (6-digit, 5-minute expiry) via email
- **Password reset** via time-boxed email links (15-minute expiry)
- Bcrypt password hashing
- Server-side session management
- Forced password reset on first login

---

## Architecture

```
┌────────────────────────┐        ┌──────────────────────┐        ┌──────────────────┐
│   Browser (Jinja2 UI)  │ <────> │  Flask App (app.py)  │ <────> │  MySQL Database  │
└────────────────────────┘        └──────────┬───────────┘        └──────────────────┘
                                             │
                                             ▼
                                   ┌─────────────────────┐
                                   │  SMTP (Gmail)       │
                                   │  OTP & reset mail   │
                                   └─────────────────────┘
```

A high-level ERD diagram is available in [`other/ERP.svg`](other/ERP.svg).

---

## Tech Stack

| Layer          | Technology                                     |
| -------------- | ---------------------------------------------- |
| Backend        | Python 3.9+, Flask, Flask-Bcrypt               |
| Database       | MySQL 8.0+ (tested on MySQL 9.4)               |
| Templating     | Jinja2                                         |
| Frontend       | HTML5, CSS3, Vanilla JS, Chart.js (CDN)        |
| Email          | SMTP (Gmail App Passwords)                     |
| Auth           | Bcrypt + OTP + session cookies                 |

---

## Project Structure

```
.
├── app.py                    # Flask application entry point and routes
├── db.py                     # MySQL connection factory
├── hash_passwords.py         # Utility: bulk-hash seed passwords
├── migrate_semester.py       # Utility: semester migration script
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── frontend/                 # Jinja2 templates
│   ├── base.html
│   ├── home.html
│   ├── student/              # Student portal templates
│   ├── faculty/              # Faculty portal templates
│   ├── admin/                # Admin portal templates
│   └── partials/             # Shared partials (navbar, etc.)
├── static/
│   ├── css/style.css
│   ├── js/script.js
│   └── icons/
├── sql/
│   ├── schema.sql            # Database schema (tables, FKs, indexes)
│   ├── seed.sql              # Sample data
│   └── migrations/           # Idempotent schema migrations
├── utils/
│   ├── auth.py               # Session & role guards
│   └── email_utils.py        # SMTP helpers (OTP, password reset, async)
├── tests/                    # pytest smoke tests
├── test/                     # Analytics/plot sandbox
├── Dockerfile                # Production image (gunicorn + healthcheck)
├── docker-compose.yml        # Local stack: app + MySQL + Redis
├── .github/workflows/ci.yml  # GitHub Actions CI
└── other/
    └── ERP.svg               # Architecture/ERD diagram
```

---

## Prerequisites

- **Python 3.9+**
- **MySQL 8.0+** running locally or reachable over the network
- **A Gmail account with an App Password** (for OTP + password reset emails)
  - See Google's [App Passwords docs](https://support.google.com/accounts/answer/185833)

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/aakri0/student-erp-management-system.git
cd student-erp-management-system

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your DB credentials, SMTP credentials, and a secure SECRET_KEY

# 5. Initialize the database
mysql -u root -p < sql/schema.sql
mysql -u root -p ERP < sql/seed.sql   # optional: loads sample data

# 6. Hash any plaintext seed passwords (if you loaded seed.sql)
python hash_passwords.py

# 7. Run the app
python app.py
```

The app will be available at **http://localhost:5000**.

---

## Configuration

All configuration is driven by environment variables loaded from a `.env` file in the project root. Copy `.env.example` to `.env` and fill in values.

| Variable                | Description                                                 | Example                        |
| ----------------------- | ----------------------------------------------------------- | ------------------------------ |
| `FLASK_SECRET_KEY`      | Flask session signing key (long random string, **required**)| `openssl rand -hex 32` output  |
| `FLASK_DEBUG`           | Enable debug mode (`0` in production)                       | `0`                            |
| `FLASK_HOST`            | Bind host                                                   | `127.0.0.1`                    |
| `FLASK_PORT`            | Bind port                                                   | `5000`                         |
| `SESSION_COOKIE_SECURE` | `1` in production (HTTPS); `0` for local HTTP dev           | `0`                            |
| `LOG_LEVEL`             | `DEBUG`, `INFO`, `WARNING`, or `ERROR`                      | `INFO`                         |
| `DB_HOST`               | MySQL host                                                  | `localhost`                    |
| `DB_PORT`               | MySQL port                                                  | `3306`                         |
| `DB_USER`               | MySQL user                                                  | `erp_user`                     |
| `DB_PASSWORD`           | MySQL password                                              | `••••••••`                     |
| `DB_NAME`               | MySQL database name                                         | `ERP`                          |
| `SMTP_SERVER`           | SMTP host                                                   | `smtp.gmail.com`               |
| `SMTP_PORT`             | SMTP port (STARTTLS)                                        | `587`                          |
| `EMAIL_ADDRESS`         | Sender email                                                | `your.erp@gmail.com`           |
| `EMAIL_PASSWORD`        | Gmail **App Password** (not your account password)          | `abcd efgh ijkl mnop`          |
| `EMAIL_SEND_SYNC`       | `1` to block on send; `0` (default) dispatches on a thread  | `0`                            |
| `SMTP_TIMEOUT`          | SMTP socket timeout (seconds)                               | `15`                           |
| `BCRYPT_LOG_ROUNDS`     | bcrypt cost factor (12 recommended for 2026 hardware)       | `12`                           |
| `RATELIMIT_STORAGE_URI` | Backend for Flask-Limiter (`memory://` or `redis://host:6379`) — **must be Redis/Memcached when running >1 worker** | `redis://localhost:6379`       |

> **Never commit your `.env` file.** It is included in `.gitignore`.

---

## Database Setup

The schema defines the following core entities:

- `users` — identity table (email, hashed password, role)
- `students`, `faculty` — role-specific profile extensions
- `departments` — organizational units
- `courses`, `enrollments`, `grade_components` — academic records
- `swd_requests` — student welfare requests
- `documents` — uploaded artefacts
- `otp_verification`, `password_resets` — auth state
- `audit_logs` — administrator action trail

Initialize with:

```bash
mysql -u root -p < sql/schema.sql
mysql -u root -p ERP < sql/seed.sql    # optional sample data
python hash_passwords.py               # converts plaintext seed passwords to bcrypt
```

---

## Running the Application

**Development:**

```bash
python app.py
```

**Production (example with Gunicorn):**

```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

For production deployments you should also:
- Set `FLASK_DEBUG=0` and `SESSION_COOKIE_SECURE=1`
- Put the app behind a reverse proxy (Nginx, Caddy) terminating TLS
- Point `RATELIMIT_STORAGE_URI` at Redis/Memcached (the in-memory default
  silently breaks under multiple workers)
- Use a managed MySQL instance with automated backups
- Rotate `FLASK_SECRET_KEY` and credentials regularly
- Probe `GET /healthz` from your load balancer or uptime monitor — it
  returns `200 {"status":"ok","db":"ok"}` when the app and DB are healthy
  and `503` otherwise

---

## Docker

A `Dockerfile` and `docker-compose.yml` are provided. The compose stack
brings up MySQL 8.4, Redis (for rate-limiting), and the Flask app under
Gunicorn with a health check.

```bash
cp .env.example .env          # fill in FLASK_SECRET_KEY, DB_PASSWORD, EMAIL_*
docker compose up --build
```

The app will be on `http://localhost:8000`. The MySQL volume `db_data`
persists across restarts.

The image runs as a non-root `appuser` (uid 1000) and uses a multi-stage,
slim Python base. CI builds the image on every push to verify it stays
buildable.

---

## Tests & CI

A small smoke-test suite lives in `tests/`. It covers the contract that
doesn't require a live database — security headers, CSRF rejection,
`/healthz` behaviour, basic routing.

```bash
pytest -v
```

GitHub Actions runs the suite on Python 3.11 and 3.12 on every push and
pull request, plus a Docker build smoke test (see
`.github/workflows/ci.yml`).

Integration tests live in `tests/test_integration.py` and use the
`tests/conftest_integration.py` fixture, which creates a disposable
`ERP_TEST_<pid>` database, loads `sql/schema.sql` plus every file in
`sql/migrations/`, runs the test, and drops the database. They're skipped
automatically when MySQL isn't reachable, so the suite still passes on a
laptop with no server.

To run them, point at a MySQL instance you don't mind getting a temporary
DB created on:

```bash
DB_HOST=127.0.0.1 DB_USER=root DB_PASSWORD=secret pytest tests/test_integration.py
```

---

## Operations

### Backups

`scripts/backup_db.sh` produces a compressed `mysqldump` of `DB_NAME`,
rotates older files, and (optionally) uploads to S3. It reads its
credentials from the same env vars the app uses.

```bash
# Local-only: writes ./backups/ERP-<timestamp>.sql.gz, keeps last 14
./scripts/backup_db.sh

# Also upload to S3
./scripts/backup_db.sh s3://my-bucket/erp-backups
```

A typical cron entry on the app host:

```cron
30 2 * * *  cd /opt/erp && ./scripts/backup_db.sh s3://my-bucket/erp-backups \
              >> /var/log/erp-backup.log 2>&1
```

Test restores periodically — backups you haven't restored from are not
backups.

### Health & readiness probes

Two endpoints are exposed for orchestration / uptime monitoring:

| Path       | Purpose                                            | Failure modes                              |
| ---------- | -------------------------------------------------- | ------------------------------------------ |
| `/healthz` | Liveness + DB ping. Cheap; safe to call frequently | DB down → 503                              |
| `/readyz`  | Liveness + DB + Redis (if configured) + SMTP       | Any configured dep unreachable → 503       |

Point your load balancer (or `docker-compose` healthcheck — already wired)
at `/healthz`. Point an external uptime monitor (UptimeRobot, BetterStack,
Healthchecks.io) at `/readyz` so degradation in Redis or SMTP also pages.

### Logs

Logs go to stdout in the format
`%(asctime)s %(levelname)s %(name)s: %(message)s`. The Docker image runs
Gunicorn with `--access-logfile -` so request logs land on stdout too.

For aggregation, the standard pattern is:

- **Self-hosted VPS:** ship stdout to journald (already automatic under
  systemd) and forward with `vector` / `promtail` to Loki or Elastic.
- **Docker / k8s:** the runtime captures stdout; ship via the cluster's
  log router (`fluent-bit`, `vector`).
- **Cheapest hosted option:** Better Stack Logs or Grafana Cloud — both
  have free tiers that handle this volume.

Set `LOG_LEVEL=DEBUG` in `.env` to surface the SQL chatter and rate-limit
decisions while debugging; default to `INFO` everywhere else.

---

## Default Roles & Workflows

| Role    | Login route            | Primary capabilities                                  |
| ------- | ---------------------- | ----------------------------------------------------- |
| Student | `/student_login`       | View grades, simulate CGPA, submit SWD requests       |
| Faculty | `/faculty_login`       | Manage courses, grade students, process requests      |
| Admin   | `/admin_login`         | Manage users, departments, analytics, audit log       |

Login flow: **email + password → 6-digit OTP sent via email → dashboard**.

---

## Security Notes

- Passwords are stored as **bcrypt** hashes (`flask-bcrypt`) with a 12-round cost factor (configurable via `BCRYPT_LOG_ROUNDS`); minimum length 8 on reset.
- OTPs are bcrypt-hashed at rest and expire after **5 minutes**; password reset tokens are UUID v4, single-use, and expire after **15 minutes**.
- Admin-created accounts receive a one-time random password via `secrets.token_urlsafe` and are forced to reset on first login.
- Session cookies are `HttpOnly` + `SameSite=Lax` by default; set `SESSION_COOKIE_SECURE=1` in production to require HTTPS.
- Role-based guards (`session['role']`) are checked on every student/faculty/admin route; cross-role access redirects to the appropriate login.
- Secrets are loaded from environment variables; **nothing sensitive should be committed**.
- `FLASK_SECRET_KEY` must be long and random in production — regenerate with `openssl rand -hex 32`.
- If you are forking this repository, **rotate any credentials** that may have appeared in earlier commits and purge history with `git filter-repo` or BFG.
- Use **Gmail App Passwords**, never your primary Google password.
- Every state-changing form carries a `{{ csrf_token() }}` input, validated globally by Flask-WTF's `CSRFProtect`.
- Login, OTP, password-reset, and resend endpoints are rate-limited with Flask-Limiter (in-memory by default; point `RATELIMIT_STORAGE_URI` at Redis/Memcached for multi-process deployments).
- Database connections opened via `get_connection()` inside a request are tracked on `flask.g` and closed in `teardown_appcontext`, so a raised exception mid-route never leaks a connection.
- Security headers (CSP, HSTS, X-Frame-Options=DENY, X-Content-Type-Options, Referrer-Policy) are set globally by Flask-Talisman; HSTS and force-https activate when `SESSION_COOKIE_SECURE=1`.
- OTP and password-reset emails are dispatched on a background daemon thread, so a slow Gmail upstream cannot stall a request worker. Failures are logged via `logger.exception` (set `EMAIL_SEND_SYNC=1` in tests to surface errors).
- `audit_logs` captures the originating IP (`X-Forwarded-For` aware) and User-Agent for every state-changing admin/faculty action.

---

## Contributing

Contributions are welcome. Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines on branching, commit style, and opening pull requests.

---

## License

Released under the **MIT License**. See [`LICENSE`](LICENSE) for the full text.
