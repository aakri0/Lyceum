"""Admin-facing routes: login, dashboard, analytics, user/dept management.

Routes registered on the shared ``app`` object via ``@app.route``.
Endpoint names match function names so existing ``url_for`` calls in
templates continue to resolve unchanged.
"""

import csv
import io
import random
import secrets

from datetime import date, datetime, timedelta

from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from mysql.connector import Error

from app import (
    _audit,
    _clear_login_attempts,
    _is_locked,
    _notify,
    _paginate,
    _record_failed_login,
    _swd_event,
    app,
    bcrypt,
    csrf,
    limiter,
    logger,
)
from db import get_connection
from utils.email_utils import send_otp_email, send_password_reset_email
from forms import (
    AssignSectionForm,
    BulkPromoteForm,
    CreateUserForm,
    DepartmentForm,
    EditFacultyForm,
    EditStudentForm,
    ForwardRequestForm,
    LoginForm,
    ResolveRequestForm,
    SectionForm,
    UpdateSemesterForm,
)


# =============================================================
@app.route('/admin_login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def admin_login():
    if request.method == 'POST':
        form = LoginForm(request.form)
        if not form.validate():
            flash("Please enter a valid email and password.", "danger")
            return render_template('admin/admin_login.html')
        email = form.email.data.strip()
        password = form.password.data

        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        if _is_locked(cur, email):
            conn.close()
            flash("Account temporarily locked due to too many failed attempts. "
                  "Try again later or use Forgot Password.", "danger")
            return render_template('admin/admin_login.html')

        cur.execute("""
            SELECT user_id, password, email
            FROM users
            WHERE email=%s AND role='admin'
        """, (email,))
        user = cur.fetchone()

        if user and bcrypt.check_password_hash(user['password'], password):
            _clear_login_attempts(cur, email)
            conn.commit()
            conn.close()
            session.clear()
            session['temp_user'] = user['user_id']
            session['otp_role'] = 'admin'

            plain_otp = str(random.randint(100000, 999999))
            hashed_otp = bcrypt.generate_password_hash(plain_otp).decode()

            conn = get_connection()
            
            cur = conn.cursor()
            cur.execute("DELETE FROM otp_verification WHERE user_id=%s", (user['user_id'],))
            cur.execute("""
                INSERT INTO otp_verification (user_id, otp, expires_at)
                VALUES (%s, %s, NOW() + INTERVAL 5 MINUTE)
            """, (user['user_id'], hashed_otp))
            conn.commit()
            conn.close()

            send_otp_email(user['email'], plain_otp)
            flash("OTP sent to your email", "info")
            return redirect(url_for('verify_otp'))

        locked = _record_failed_login(cur, email)
        conn.commit()
        conn.close()
        if locked:
            flash("Too many failed attempts. Account locked for 15 minutes.", "danger")
        else:
            flash("Invalid credentials", "danger")

    return render_template('admin/admin_login.html')


@app.route('/admin_dashboard')
def admin_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))
    return render_template('admin/admin_dashboard.html')

@app.route('/admin_analytics')
def admin_analytics():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if not start_date:
        start_date = '2000-01-01'
    if not end_date:
        end_date = date.today().isoformat()

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT COUNT(*) total FROM students")
    total_students = cur.fetchone()['total']

    cur.execute("SELECT COUNT(*) total FROM faculty")
    total_faculty = cur.fetchone()['total']

    cur.execute("""
        SELECT COUNT(*) total
        FROM swd_requests
        WHERE DATE(created_at) BETWEEN %s AND %s
    """, (start_date, end_date))
    total_requests = cur.fetchone()['total']

    cur.execute("""
        SELECT status, COUNT(*) count
        FROM swd_requests
        WHERE DATE(created_at) BETWEEN %s AND %s
        GROUP BY status
    """, (start_date, end_date))
    status_data = cur.fetchall()

    cur.execute("""
        SELECT category, COUNT(*) count
        FROM swd_requests
        WHERE DATE(created_at) BETWEEN %s AND %s
        GROUP BY category
    """, (start_date, end_date))
    category_data = cur.fetchall()

    cur.execute("""
        SELECT d.dept_name, COUNT(*) count
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN departments d ON s.dept_id = d.dept_id
        WHERE DATE(r.created_at) BETWEEN %s AND %s
        GROUP BY d.dept_name
    """, (start_date, end_date))
    dept_data = cur.fetchall()

    conn.close()

    return render_template(
        'admin/admin_analytics.html',
        total_students=total_students,
        total_faculty=total_faculty,
        total_requests=total_requests,
        status_data=status_data,
        category_data=category_data,
        dept_data=dept_data,
        start_date=start_date,
        end_date=end_date
    )


@app.route('/admin_audit_logs')
def admin_audit_logs():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    page, per_page, offset = _paginate(default_per_page=100)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT COUNT(*) AS c FROM audit_logs")
    total = cur.fetchone()["c"]

    cur.execute("""
        SELECT a.action, a.created_at, a.ip_address, a.user_agent, u.email
        FROM audit_logs a
        JOIN users u ON a.user_id=u.user_id
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    logs = cur.fetchall()
    conn.close()

    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
        "has_prev": page > 1,
        "has_next": offset + per_page < total,
    }
    return render_template('admin/audit_logs.html', logs=logs, pagination=pagination)

@app.route('/admin_export_csv')
def admin_export_csv():
    if 'user_id' not in session:
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT r.req_id, s.roll_no, d.dept_name,
               r.category, r.status, r.created_at
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN departments d ON s.dept_id = d.dept_id
        ORDER BY r.created_at DESC
    """)
    rows = cur.fetchall()
    conn.close()

    # Create in-memory text buffer
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "Request ID",
        "Roll No",
        "Department",
        "Category",
        "Status",
        "Created At"
    ])

    # Rows
    for r in rows:
        writer.writerow([
            r['req_id'],
            r['roll_no'],
            r['dept_name'],
            r['category'],
            r['status'],
            r['created_at']
        ])

    # Build response
    response = Response(
        output.getvalue(),
        mimetype='text/csv'
    )
    response.headers["Content-Disposition"] = \
        "attachment; filename=erp_requests_report.csv"

    return response

@app.route('/admin_create_user', methods=['GET', 'POST'])
def admin_create_user():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        form = CreateUserForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            return render_template('admin/create_user.html')
        name = form.name.data.strip()
        email = form.email.data.strip()
        role = form.role.data

        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # 🔒 Check duplicate email
        cur.execute("SELECT user_id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            conn.close()
            flash("User with this email already exists.", "danger")
            return redirect(url_for('admin_create_user'))

        temp_password = secrets.token_urlsafe(9)
        hashed = bcrypt.generate_password_hash(temp_password).decode()

        try:
            # 1️⃣ Insert into users
            cur.execute("""
                INSERT INTO users (name, email, password, role, force_reset)
                VALUES (%s, %s, %s, %s, 1)
            """, (name, email, hashed, role))

            user_id = cur.lastrowid

            # 2️⃣ Insert role-specific data
            if role == 'student':
                cur.execute("""
                    INSERT INTO students (user_id, roll_no, dept_id, year_of_study, current_semester)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    user_id,
                    form.roll_no.data,
                    form.dept_id.data,
                    form.year_of_study.data,
                    form.current_semester.data,
                ))

            elif role == 'faculty':
                cur.execute("""
                    INSERT INTO faculty (user_id, dept_id)
                    VALUES (%s, %s)
                """, (user_id, form.dept_id.data))

            _audit(cur, session['user_id'], f"Created {role} user_id={user_id} ({email})")
            conn.commit()
            flash(
                f"User created successfully. Temporary password: {temp_password} "
                f"— share securely; the user must change it on first login.",
                "success",
            )

        except Error:
            conn.rollback()
            logger.exception("Error creating user")
            flash("Error creating user.", "danger")

        finally:
            conn.close()

    return render_template('admin/create_user.html')

@app.route('/admin_requests')
def admin_requests():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    # Fetch all requests with student and assigned faculty info
    cur.execute("""
        SELECT r.req_id, r.category, r.description, r.status, r.created_at,
               r.assigned_faculty_id,
               u.name as student_name, s.roll_no, s.dept_id,
               f_user.name as assigned_faculty_name
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        LEFT JOIN faculty f ON r.assigned_faculty_id = f.faculty_id
        LEFT JOIN users f_user ON f.user_id = f_user.user_id
        ORDER BY r.created_at DESC
    """)
    requests = cur.fetchall()
    
    # Fetch all faculty for the forward dropdown
    cur.execute("""
        SELECT f.faculty_id, u.name, f.dept_id
        FROM faculty f
        JOIN users u ON f.user_id = u.user_id
        ORDER BY u.name
    """)
    faculty_list = cur.fetchall()
    
    conn.close()

    return render_template('admin/admin_requests.html', requests=requests, faculty_list=faculty_list)

@app.route('/admin_resolve_request/<int:req_id>', methods=['POST'])
def admin_resolve_request(req_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    form = ResolveRequestForm(request.form)
    if not form.validate():
        flash("Invalid action", "danger")
        return redirect(url_for('admin_requests'))
    action = form.action.data

    conn = get_connection()
    cur = conn.cursor()
    
    # If resetting to pending, also clear the faculty assignment
    if action == 'pending':
        cur.execute("""
            UPDATE swd_requests
            SET status = %s, assigned_faculty_id = NULL
            WHERE req_id = %s
        """, (action, req_id))
    else:
        cur.execute("""
            UPDATE swd_requests
            SET status = %s
            WHERE req_id = %s
        """, (action, req_id))

    _audit(cur, session['user_id'], f"Set request {req_id} status={action}")
    _swd_event(cur, req_id, session['user_id'], f"status:{action}")

    # Notify the student of the status change.
    cur2 = conn.cursor(dictionary=True)
    cur2.execute("""
        SELECT u.user_id, r.category
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        WHERE r.req_id = %s
    """, (req_id,))
    row = cur2.fetchone()
    cur2.close()

    # B7: auto-issue bonafide certificate on approve.
    serial = None
    if row and row['category'] == 'Bonafide':
        cur_dict = conn.cursor(dictionary=True)
        try:
            serial = _maybe_issue_bonafide(cur_dict, req_id, action, session['user_id'])
        except Exception:
            logger.exception("bonafide PDF generation failed")
        cur_dict.close()

    if row:
        link = url_for('student_requests')
        msg = f"Your {row['category']} request was {action}."
        if serial:
            msg += f" Certificate {serial} is ready to download."
            link = url_for('download_bonafide', serial_no=serial)
        _notify(cur, row['user_id'], 'request_status', msg, link)

    conn.commit()
    conn.close()

    flash(
        f"Request {action} successfully" + (f" — bonafide {serial}" if serial else ""),
        "success",
    )
    return redirect(url_for('admin_requests'))

@app.route('/admin_forward_request/<int:req_id>', methods=['POST'])
def admin_forward_request(req_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    form = ForwardRequestForm(request.form)
    if not form.validate():
        flash("Please select a faculty member", "danger")
        return redirect(url_for('admin_requests'))
    faculty_id = form.faculty_id.data

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE swd_requests
        SET assigned_faculty_id = %s
        WHERE req_id = %s
    """, (faculty_id, req_id))
    _audit(cur, session['user_id'], f"Forwarded request {req_id} to faculty_id={faculty_id}")
    _swd_event(cur, req_id, session['user_id'], f"forwarded:{faculty_id}")

    # Notify the assigned faculty member.
    cur2 = conn.cursor(dictionary=True)
    cur2.execute("""
        SELECT u.user_id, r.category
        FROM faculty f
        JOIN users u ON f.user_id = u.user_id, swd_requests r
        WHERE f.faculty_id = %s AND r.req_id = %s
    """, (faculty_id, req_id))
    row = cur2.fetchone()
    cur2.close()
    if row:
        _notify(
            cur, row['user_id'], 'request_assigned',
            f"A new {row['category']} request has been assigned to you.",
            url_for('faculty_requests'),
        )

    conn.commit()
    conn.close()

    flash("Request forwarded to faculty successfully", "success")
    return redirect(url_for('admin_requests'))






@app.route('/admin_manage_students')
def admin_manage_students():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    page, per_page, offset = _paginate(default_per_page=50)
    q = (request.args.get('q') or '').strip()
    dept_id_filter = request.args.get('dept_id', type=int)
    year_filter = request.args.get('year', type=int)

    where = []
    params: list = []
    if q:
        where.append("(u.name LIKE %s OR u.email LIKE %s OR s.roll_no LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if dept_id_filter:
        where.append("s.dept_id = %s")
        params.append(dept_id_filter)
    if year_filter:
        where.append("s.year_of_study = %s")
        params.append(year_filter)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute(f"""
        SELECT COUNT(*) AS c FROM students s JOIN users u ON s.user_id=u.user_id {where_sql}
    """, tuple(params))
    total = cur.fetchone()["c"]

    cur.execute(f"""
        SELECT s.student_id, s.roll_no, s.year_of_study, s.current_semester, s.dept_id,
               u.name, u.email, d.dept_name
        FROM students s
        JOIN users u ON s.user_id = u.user_id
        JOIN departments d ON s.dept_id = d.dept_id
        {where_sql}
        ORDER BY d.dept_name, s.year_of_study, s.roll_no
        LIMIT %s OFFSET %s
    """, tuple(params + [per_page, offset]))
    students = cur.fetchall()

    cur.execute("SELECT dept_id, dept_name FROM departments ORDER BY dept_name")
    departments = cur.fetchall()
    conn.close()

    # Structure for the template: { 'Dept A': { 1: [students], 2: [...] } }
    structured_data: dict = {}
    for student in students:
        dept = student['dept_name']
        year = student['year_of_study']
        structured_data.setdefault(dept, {}).setdefault(year, []).append(student)

    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
        "has_prev": page > 1,
        "has_next": offset + per_page < total,
    }
    return render_template(
        'admin/manage_students.html',
        structured_data=structured_data,
        pagination=pagination,
        departments=departments,
        q=q, dept_id_filter=dept_id_filter, year_filter=year_filter,
    )

@app.route('/admin_update_semester/<int:student_id>', methods=['POST'])
def admin_update_semester(student_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    
    form = UpdateSemesterForm(request.form)
    if not form.validate():
        flash("Invalid semester value.", "danger")
        return redirect(url_for('admin_manage_students'))
    new_semester = form.semester.data

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE students
        SET current_semester = %s
        WHERE student_id = %s
    """, (new_semester, student_id))

    _audit(cur, session['user_id'], f"Updated student_id={student_id} semester={new_semester}")
    conn.commit()
    conn.close()

    flash(f"Student updated to Semester {new_semester}", "success")
    return redirect(url_for('admin_manage_students'))

@app.route('/admin_bulk_promote', methods=['POST'])
def admin_bulk_promote():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    form = BulkPromoteForm(request.form)
    if not form.validate():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for('admin_manage_students'))
    from_sem = form.from_semester.data
    to_sem = form.to_semester.data

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE students
        SET current_semester = %s
        WHERE current_semester = %s
    """, (to_sem, from_sem))

    rows_affected = cur.rowcount
    _audit(
        cur,
        session['user_id'],
        f"Bulk-promoted {rows_affected} students from sem {from_sem} -> sem {to_sem}",
    )
    conn.commit()
    conn.close()

    if rows_affected > 0:
        flash(f"Successfully promoted {rows_affected} students from Sem {from_sem} to Sem {to_sem}.", "success")
    else:
        flash(f"No students found in Semester {from_sem}.", "info")

    return redirect(url_for('admin_manage_students'))


@app.route('/admin_delete_student/<int:student_id>', methods=['POST'])
def admin_delete_student(student_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    # Get user_id associated with student
    cur.execute("SELECT user_id FROM students WHERE student_id=%s", (student_id,))
    student = cur.fetchone()
    
    if student:
        user_id = student['user_id']
        cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
        _audit(cur, session['user_id'], f"Deleted student_id={student_id} user_id={user_id}")
        conn.commit()
        flash("Student deleted successfully", "success")
    else:
        flash("Student not found", "danger")
        
    conn.close()
    return redirect(url_for('admin_manage_students'))

@app.route('/admin_edit_student/<int:student_id>', methods=['GET', 'POST'])
def admin_edit_student(student_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        form = EditStudentForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            conn.close()
            return redirect(url_for('admin_edit_student', student_id=student_id))
        name = form.name.data.strip()
        email = form.email.data.strip()
        roll_no = form.roll_no.data
        year = form.year_of_study.data
        current_sem = form.current_semester.data
        dept_id = form.dept_id.data

        # Get user_id
        cur.execute("SELECT user_id FROM students WHERE student_id=%s", (student_id,))
        res = cur.fetchone()
        if res:
            user_id = res['user_id']

            # Update Users table
            cur.execute("UPDATE users SET name=%s, email=%s WHERE user_id=%s", (name, email, user_id))

            # Update Students table
            cur.execute("""
                UPDATE students
                SET roll_no=%s, year_of_study=%s, current_semester=%s, dept_id=%s
                WHERE student_id=%s
            """, (roll_no, year, current_sem, dept_id, student_id))

            _audit(cur, session['user_id'], f"Edited student_id={student_id} ({email})")
            conn.commit()
            flash("Student updated successfully", "success")
            conn.close()
            return redirect(url_for('admin_manage_students'))
            
    # GET: Fetch student data and departments
    cur.execute("""
        SELECT s.student_id, s.roll_no, s.year_of_study, s.current_semester, s.dept_id,
               u.name, u.email, d.dept_name
        FROM students s
        JOIN users u ON s.user_id = u.user_id
        JOIN departments d ON s.dept_id = d.dept_id
        WHERE s.student_id=%s
    """, (student_id,))
    student = cur.fetchone()
    
    cur.execute("SELECT * FROM departments")
    departments = cur.fetchall()
    
    conn.close()
    
    if not student:
        flash("Student not found", "danger")
        return redirect(url_for('admin_manage_students'))
        
    return render_template('admin/edit_student.html', student=student, departments=departments)


# =============================================================
# MAIN
# =============================================================
@app.route('/admin_manage_faculty')
def admin_manage_faculty():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    page, per_page, offset = _paginate(default_per_page=50)
    q = (request.args.get('q') or '').strip()
    dept_id_filter = request.args.get('dept_id', type=int)

    where = []
    params: list = []
    if q:
        where.append("(u.name LIKE %s OR u.email LIKE %s)")
        like = f"%{q}%"
        params.extend([like, like])
    if dept_id_filter:
        where.append("f.dept_id = %s")
        params.append(dept_id_filter)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute(f"""
        SELECT COUNT(*) AS c FROM faculty f JOIN users u ON f.user_id=u.user_id {where_sql}
    """, tuple(params))
    total = cur.fetchone()["c"]

    cur.execute(f"""
        SELECT f.faculty_id, f.dept_id,
               u.name, u.email, d.dept_name
        FROM faculty f
        JOIN users u ON f.user_id = u.user_id
        JOIN departments d ON f.dept_id = d.dept_id
        {where_sql}
        ORDER BY d.dept_name, u.name
        LIMIT %s OFFSET %s
    """, tuple(params + [per_page, offset]))
    faculty_list = cur.fetchall()

    cur.execute("SELECT dept_id, dept_name FROM departments ORDER BY dept_name")
    departments = cur.fetchall()
    conn.close()

    # Structure data: { 'Dept A': [faculty, ...], ... }
    structured_data = {}
    for f in faculty_list:
        dept = f['dept_name']
        if dept not in structured_data:
            structured_data[dept] = []
        structured_data[dept].append(f)

    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
        "has_prev": page > 1,
        "has_next": offset + per_page < total,
    }
    return render_template(
        'admin/manage_faculty.html',
        structured_data=structured_data,
        pagination=pagination,
        departments=departments,
        q=q, dept_id_filter=dept_id_filter,
    )

@app.route('/admin_delete_faculty/<int:faculty_id>', methods=['POST'])
def admin_delete_faculty(faculty_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    cur.execute("SELECT user_id FROM faculty WHERE faculty_id=%s", (faculty_id,))
    faculty = cur.fetchone()
    
    if faculty:
        user_id = faculty['user_id']
        cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
        _audit(cur, session['user_id'], f"Deleted faculty_id={faculty_id} user_id={user_id}")
        conn.commit()
        flash("Faculty deleted successfully", "success")
    else:
        flash("Faculty not found", "danger")

    conn.close()
    return redirect(url_for('admin_manage_faculty'))

@app.route('/admin_edit_faculty/<int:faculty_id>', methods=['GET', 'POST'])
def admin_edit_faculty(faculty_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        form = EditFacultyForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            conn.close()
            return redirect(url_for('admin_edit_faculty', faculty_id=faculty_id))
        name = form.name.data.strip()
        email = form.email.data.strip()
        dept_id = form.dept_id.data

        cur.execute("SELECT user_id FROM faculty WHERE faculty_id=%s", (faculty_id,))
        res = cur.fetchone()
        if res:
            user_id = res['user_id']
            cur.execute("UPDATE users SET name=%s, email=%s WHERE user_id=%s", (name, email, user_id))
            cur.execute("UPDATE faculty SET dept_id=%s WHERE faculty_id=%s", (dept_id, faculty_id))
            _audit(cur, session['user_id'], f"Edited faculty_id={faculty_id} ({email}) dept_id={dept_id}")
            conn.commit()
            flash("Faculty updated successfully", "success")
            conn.close()
            return redirect(url_for('admin_manage_faculty'))
            
    cur.execute("""
        SELECT f.faculty_id, f.dept_id,
               u.name, u.email, d.dept_name
        FROM faculty f
        JOIN users u ON f.user_id = u.user_id
        JOIN departments d ON f.dept_id = d.dept_id
        WHERE f.faculty_id=%s
    """, (faculty_id,))
    faculty = cur.fetchone()
    
    cur.execute("SELECT * FROM departments")
    departments = cur.fetchall()
    
    conn.close()
    
    if not faculty:
        flash("Faculty not found", "danger")
        return redirect(url_for('admin_manage_faculty'))
        
    return render_template('admin/edit_faculty.html', faculty=faculty, departments=departments)


# =============================================================
# MAIN
# =============================================================
@app.route('/admin_manage_departments')
def admin_manage_departments():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM departments ORDER BY dept_id")
    departments = cur.fetchall()
    conn.close()
    
    return render_template('admin/manage_departments.html', departments=departments)

@app.route('/admin_add_department', methods=['POST'])
def admin_add_department():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    form = DepartmentForm(request.form)
    if not form.validate():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for('admin_manage_departments'))
    dept_name = form.dept_name.data.strip()

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO departments (dept_name) VALUES (%s)", (dept_name,))
        new_dept_id = cur.lastrowid
        _audit(cur, session['user_id'], f"Created department_id={new_dept_id} ({dept_name})")
        conn.commit()
        flash("Department added successfully", "success")
    except Exception:
        logger.exception("Error adding department")
        flash("Error adding department. Please try again.", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('admin_manage_departments'))

@app.route('/admin_edit_department/<int:dept_id>', methods=['GET', 'POST'])
def admin_edit_department(dept_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    if request.method == 'POST':
        form = DepartmentForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            conn.close()
            return redirect(url_for('admin_edit_department', dept_id=dept_id))
        dept_name = form.dept_name.data.strip()
        cur.execute("UPDATE departments SET dept_name=%s WHERE dept_id=%s", (dept_name, dept_id))
        _audit(cur, session['user_id'], f"Edited department_id={dept_id} name={dept_name!r}")
        conn.commit()
        conn.close()
        flash("Department updated successfully", "success")
        return redirect(url_for('admin_manage_departments'))
        
    cur.execute("SELECT * FROM departments WHERE dept_id=%s", (dept_id,))
    department = cur.fetchone()
    conn.close()
    
    if not department:
        flash("Department not found", "danger")
        return redirect(url_for('admin_manage_departments'))
        
    return render_template('admin/edit_department.html', department=department)

@app.route('/admin_delete_department/<int:dept_id>', methods=['POST'])
def admin_delete_department(dept_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
        
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM departments WHERE dept_id=%s", (dept_id,))
        _audit(cur, session['user_id'], f"Deleted department_id={dept_id}")
        conn.commit()
        flash("Department deleted successfully", "success")
    except Exception:
        # Constraint error likely if students/faculty exist
        logger.exception("Failed to delete department %s", dept_id)
        flash("Cannot delete department. It may be linked to existing students or faculty.", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('admin_manage_departments'))



# =============================================================
# COURSE-FACULTY ALLOTMENT (B11)
# =============================================================
@app.route('/admin_course_allotment')
def admin_course_allotment():
    """Show every section with its course + faculty + roster size.

    Filterable by course or faculty via query string. New sections are
    created via /admin_section_create; existing ones via the inline edit
    form on this page.
    """
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    course_filter = request.args.get('course_id', type=int)
    faculty_filter = request.args.get('faculty_id', type=int)

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    where = []
    params: list = []
    if course_filter:
        where.append("cs.course_id = %s")
        params.append(course_filter)
    if faculty_filter:
        where.append("cs.faculty_id = %s")
        params.append(faculty_filter)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    cur.execute(f"""
        SELECT cs.section_id, cs.course_id, cs.section_label, cs.semester,
               cs.faculty_id, cs.capacity, cs.created_at,
               c.course_name, c.dept_id, d.dept_name,
               u.name AS faculty_name, u.email AS faculty_email,
               (SELECT COUNT(*) FROM enrollments e WHERE e.section_id = cs.section_id) AS enrolled_count
        FROM course_sections cs
        JOIN courses c ON c.course_id = cs.course_id
        JOIN departments d ON c.dept_id = d.dept_id
        LEFT JOIN faculty f ON cs.faculty_id = f.faculty_id
        LEFT JOIN users u ON f.user_id = u.user_id
        {where_sql}
        ORDER BY d.dept_name, c.course_name, cs.semester, cs.section_label
    """, tuple(params))
    sections = cur.fetchall()

    # Lookup tables for the create-section form.
    cur.execute("""
        SELECT c.course_id, c.course_name, c.dept_id, d.dept_name
        FROM courses c JOIN departments d ON c.dept_id = d.dept_id
        ORDER BY d.dept_name, c.course_name
    """)
    courses = cur.fetchall()
    cur.execute("""
        SELECT f.faculty_id, u.name, f.dept_id, d.dept_name
        FROM faculty f JOIN users u ON f.user_id = u.user_id
        JOIN departments d ON f.dept_id = d.dept_id
        ORDER BY d.dept_name, u.name
    """)
    faculty_list = cur.fetchall()
    conn.close()

    return render_template(
        'admin/course_allotment.html',
        sections=sections,
        courses=courses,
        faculty_list=faculty_list,
        course_filter=course_filter,
        faculty_filter=faculty_filter,
    )


@app.route('/admin_section_create', methods=['POST'])
def admin_section_create():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    form = SectionForm(request.form)
    if not form.validate():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for('admin_course_allotment'))

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO course_sections (course_id, faculty_id, section_label, semester, capacity)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            form.course_id.data,
            form.faculty_id.data or None,
            form.section_label.data.upper(),
            form.semester.data,
            form.capacity.data or None,
        ))
        new_id = cur.lastrowid
        _audit(
            cur,
            session['user_id'],
            f"Created section_id={new_id} course_id={form.course_id.data} "
            f"label={form.section_label.data!r} sem={form.semester.data} "
            f"faculty_id={form.faculty_id.data}",
        )
        conn.commit()
        flash("Section created.", "success")
    except Error as e:
        conn.rollback()
        if e.errno == 1062:
            flash("A section with that label already exists for this course/semester.", "danger")
        else:
            logger.exception("Failed to create section")
            flash("Could not create section.", "danger")
    finally:
        conn.close()

    return redirect(url_for('admin_course_allotment'))


@app.route('/admin_section_edit/<int:section_id>', methods=['POST'])
def admin_section_edit(section_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    form = SectionForm(request.form)
    if not form.validate():
        for field, errors in form.errors.items():
            for err in errors:
                flash(f"{field}: {err}", "danger")
        return redirect(url_for('admin_course_allotment'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE course_sections
           SET course_id=%s, faculty_id=%s, section_label=%s, semester=%s, capacity=%s
         WHERE section_id=%s
    """, (
        form.course_id.data,
        form.faculty_id.data or None,
        form.section_label.data.upper(),
        form.semester.data,
        form.capacity.data or None,
        section_id,
    ))
    _audit(
        cur,
        session['user_id'],
        f"Edited section_id={section_id} course_id={form.course_id.data} "
        f"faculty_id={form.faculty_id.data} label={form.section_label.data!r}",
    )
    conn.commit()
    conn.close()
    flash("Section updated.", "success")
    return redirect(url_for('admin_course_allotment'))


@app.route('/admin_section_delete/<int:section_id>', methods=['POST'])
def admin_section_delete(section_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT COUNT(*) AS c FROM enrollments WHERE section_id=%s",
        (section_id,),
    )
    enrolled = cur.fetchone()["c"]
    if enrolled:
        conn.close()
        flash(
            f"Cannot delete: {enrolled} student(s) enrolled. "
            f"Re-allot them to another section first.",
            "danger",
        )
        return redirect(url_for('admin_course_allotment'))

    cur.execute("DELETE FROM course_sections WHERE section_id=%s", (section_id,))
    _audit(cur, session['user_id'], f"Deleted section_id={section_id}")
    conn.commit()
    conn.close()
    flash("Section deleted.", "success")
    return redirect(url_for('admin_course_allotment'))


@app.route('/admin_reallot_student', methods=['POST'])
def admin_reallot_student():
    """Move an existing enrollment from one section to another."""
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    form = AssignSectionForm(request.form)
    if not form.validate():
        flash("Invalid section assignment.", "danger")
        return redirect(url_for('admin_course_allotment'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    # Verify the target section is for the same course as the enrollment.
    cur.execute("""
        SELECT e.course_id, cs.course_id AS target_course
        FROM enrollments e, course_sections cs
        WHERE e.enrollment_id=%s AND cs.section_id=%s
    """, (form.enrollment_id.data, form.section_id.data))
    row = cur.fetchone()
    if not row or row["course_id"] != row["target_course"]:
        conn.close()
        flash("Target section is for a different course.", "danger")
        return redirect(url_for('admin_course_allotment'))

    cur.execute(
        "UPDATE enrollments SET section_id=%s WHERE enrollment_id=%s",
        (form.section_id.data, form.enrollment_id.data),
    )
    _audit(
        cur,
        session['user_id'],
        f"Re-allotted enrollment_id={form.enrollment_id.data} -> section_id={form.section_id.data}",
    )
    conn.commit()
    conn.close()
    flash("Student re-allotted.", "success")
    return redirect(url_for('admin_course_allotment'))


# =============================================================
# ANNOUNCEMENTS (B3) — admin can post to anyone
# =============================================================
@app.route('/admin_announcements', methods=['GET', 'POST'])
def admin_announcements():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    from forms import AnnouncementForm
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if request.method == 'POST':
        form = AnnouncementForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
        else:
            expires = None
            if form.expires_at.data:
                try:
                    raw = form.expires_at.data.strip().replace("T", " ")
                    if len(raw) == 10:
                        raw += " 23:59"
                    expires = datetime.strptime(raw, "%Y-%m-%d %H:%M")
                except ValueError:
                    flash("Invalid expires_at format.", "danger")
                    return redirect(url_for('admin_announcements'))

            cur.execute("""
                INSERT INTO announcements
                  (posted_by, title, body, target_dept_id, target_year,
                   target_role, target_course_id, pinned, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                session['user_id'],
                form.title.data.strip(),
                form.body.data.strip(),
                form.target_dept_id.data or None,
                form.target_year.data or None,
                form.target_role.data or None,
                form.target_course_id.data or None,
                1 if form.pinned.data else 0,
                expires,
            ))
            new_id = cur.lastrowid
            _audit(
                cur, session['user_id'],
                f"Posted announcement_id={new_id} title={form.title.data!r}",
            )
            conn.commit()
            flash("Announcement posted.", "success")
            return redirect(url_for('admin_announcements'))

    cur.execute("""
        SELECT a.announcement_id, a.title, a.pinned, a.expires_at, a.created_at,
               a.target_dept_id, a.target_year, a.target_role, a.target_course_id,
               d.dept_name, c.course_name, u.name AS poster_name
        FROM announcements a
        JOIN users u ON a.posted_by = u.user_id
        LEFT JOIN departments d ON a.target_dept_id = d.dept_id
        LEFT JOIN courses c ON a.target_course_id = c.course_id
        ORDER BY a.created_at DESC
        LIMIT 100
    """)
    items = cur.fetchall()

    cur.execute("SELECT dept_id, dept_name FROM departments ORDER BY dept_name")
    departments = cur.fetchall()
    cur.execute("SELECT course_id, course_name FROM courses ORDER BY course_name")
    courses = cur.fetchall()
    conn.close()

    return render_template(
        'admin/announcements.html',
        items=items, departments=departments, courses=courses,
    )


@app.route('/admin_announcement_delete/<int:announcement_id>', methods=['POST'])
def admin_announcement_delete(announcement_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM announcements WHERE announcement_id=%s", (announcement_id,))
    _audit(cur, session['user_id'], f"Deleted announcement_id={announcement_id}")
    conn.commit()
    conn.close()
    flash("Announcement deleted.", "success")
    return redirect(url_for('admin_announcements'))


# =============================================================
# BONAFIDE CERTIFICATES (B7)
# =============================================================
import os as _os
from io import BytesIO
from pathlib import Path as _Path

from flask import abort as _abort, send_file


def _certificate_dir() -> _Path:
    p = _Path(_os.environ.get("UPLOAD_DIR", "./uploads")).resolve() / "certificates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _generate_bonafide_pdf(student: dict, serial_no: str, issued_by_name: str) -> bytes:
    """Render a one-page bonafide certificate as a PDF and return its bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Letterhead
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(width / 2, height - 3 * cm, "ERP COLLEGE")
    c.setFont("Helvetica", 11)
    c.drawCentredString(width / 2, height - 3.7 * cm, "Office of the Registrar")
    c.line(2 * cm, height - 4.2 * cm, width - 2 * cm, height - 4.2 * cm)

    # Title
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 5.5 * cm, "BONAFIDE CERTIFICATE")

    # Serial + date
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, height - 6.3 * cm, f"Serial No: {serial_no}")
    c.drawRightString(width - 2 * cm, height - 6.3 * cm,
                      f"Date: {datetime.utcnow().strftime('%d %b %Y')}")

    # Body
    body_y = height - 8.5 * cm
    c.setFont("Helvetica", 12)
    body = (
        f"This is to certify that {student['name']} (Roll No: {student['roll_no']}) "
        f"is a bonafide student of the {student['dept_name']} department, "
        f"currently in Year {student['year_of_study']}, "
        f"Semester {student['current_semester']}.\n\n"
        f"This certificate is issued upon the request of the student for "
        f"official purposes."
    )
    text = c.beginText(2 * cm, body_y)
    text.setLeading(18)
    for paragraph in body.split("\n\n"):
        for line in _wrap(paragraph, 90):
            text.textLine(line)
        text.textLine("")
    c.drawText(text)

    # Signature block
    c.setFont("Helvetica", 11)
    c.drawString(width - 7 * cm, 4 * cm, issued_by_name)
    c.line(width - 7 * cm, 4.4 * cm, width - 2 * cm, 4.4 * cm)
    c.drawString(width - 7 * cm, 3.5 * cm, "Registrar")

    # Footer
    c.setFont("Helvetica-Oblique", 8)
    c.drawCentredString(width / 2, 1.5 * cm,
                        f"Verify at: bonafide/{serial_no}  ·  "
                        f"Generated on {datetime.utcnow().isoformat(timespec='seconds')}Z")

    c.showPage()
    c.save()
    return buf.getvalue()


def _wrap(s: str, width: int):
    out, line = [], ""
    for word in s.split():
        if len(line) + 1 + len(word) <= width:
            line = (line + " " + word).strip()
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def _maybe_issue_bonafide(cur, req_id: int, action: str, issuer_user_id: int) -> str | None:
    """If the resolved request is a Bonafide and the action is 'approved',
    create a certificate row + PDF and return the serial number. Idempotent.
    """
    if action != "approved":
        return None
    cur.execute("""
        SELECT r.req_id, r.student_id, r.category,
               s.roll_no, s.year_of_study, s.current_semester, s.dept_id,
               u.name, d.dept_name
        FROM swd_requests r
        JOIN students s ON r.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        JOIN departments d ON s.dept_id = d.dept_id
        WHERE r.req_id = %s
    """, (req_id,))
    row = cur.fetchone()
    if not row or row['category'] != 'Bonafide':
        return None

    cur.execute(
        "SELECT serial_no FROM bonafide_certificates WHERE req_id=%s",
        (req_id,),
    )
    existing = cur.fetchone()
    if existing:
        return existing['serial_no']

    cur.execute(
        "SELECT COUNT(*) AS c FROM bonafide_certificates WHERE YEAR(issued_at)=YEAR(NOW())"
    )
    n = cur.fetchone()['c'] + 1
    serial = f"BONA-{datetime.utcnow().year}-{n:04d}"

    cur.execute("SELECT name FROM users WHERE user_id=%s", (issuer_user_id,))
    issuer = cur.fetchone()
    issuer_name = issuer['name'] if issuer else "ERP Administration"

    pdf = _generate_bonafide_pdf(row, serial, issuer_name)
    out_path = _certificate_dir() / f"{serial}.pdf"
    out_path.write_bytes(pdf)

    cur.execute("""
        INSERT INTO bonafide_certificates (req_id, student_id, serial_no, issued_by)
        VALUES (%s, %s, %s, %s)
    """, (req_id, row['student_id'], serial, issuer_user_id))
    return serial


@app.route('/bonafide/<path:serial_no>')
def download_bonafide(serial_no):
    """Anyone with the URL can verify; the route also gates by login."""
    if not session.get('user_id'):
        return redirect(url_for('home'))
    safe = secure_filename_serial(serial_no)
    if safe != serial_no:
        _abort(400)
    path = _certificate_dir() / f"{serial_no}.pdf"
    if not path.exists():
        _abort(404)
    return send_file(path, mimetype="application/pdf",
                     as_attachment=False, download_name=f"{serial_no}.pdf")


def secure_filename_serial(s: str) -> str:
    """Allow only [A-Z0-9-] for serial-number paths."""
    import re
    return "".join(ch for ch in s if re.match(r"[A-Za-z0-9-]", ch))
