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
│   └── seed.sql              # Sample data
├── utils/
│   ├── auth.py               # Session & role guards
│   └── email_utils.py        # SMTP helpers (OTP, password reset)
├── test/                     # Analytics/plot sandbox
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
- Set `FLASK_DEBUG=0`
- Put the app behind a reverse proxy (Nginx, Caddy) terminating TLS
- Use a managed MySQL instance with automated backups
- Rotate `FLASK_SECRET_KEY` and credentials regularly

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

- Passwords are stored as **bcrypt** hashes (`flask-bcrypt`); minimum length 8 on reset.
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

---

## Contributing

Contributions are welcome. Please see [`CONTRIBUTING.md`](CONTRIBUTING.md) for guidelines on branching, commit style, and opening pull requests.

---

## License

Released under the **MIT License**. See [`LICENSE`](LICENSE) for the full text.
