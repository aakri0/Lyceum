"""Student-facing routes: login, dashboard, courses, requests, simulator.

Routes registered on the shared ``app`` object via ``@app.route``.
Endpoint names match function names so existing ``url_for`` calls in
templates continue to resolve unchanged.
"""

import random

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
    _announcements_for,
    _audit,
    _clear_login_attempts,
    _is_locked,
    _record_failed_login,
    app,
    bcrypt,
    csrf,
    limiter,
    logger,
)
from db import get_connection
from utils.email_utils import send_otp_email, send_password_reset_email
from forms import LoginForm, NewSWDRequestForm


# STUDENT LOGIN + OTP
# =============================================================
@app.route('/student_login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def student_login():
    if request.method == 'POST':
        form = LoginForm(request.form)
        if not form.validate():
            flash("Please enter a valid email and password.", "danger")
            return render_template('student/student_login.html')
        email = form.email.data.strip()
        password = form.password.data

        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        if _is_locked(cur, email):
            conn.close()
            flash("Account temporarily locked due to too many failed attempts. "
                  "Try again later or use Forgot Password.", "danger")
            return render_template('student/student_login.html')

        cur.execute("""
            SELECT u.user_id, u.password, u.email, s.student_id
            FROM users u
            JOIN students s ON u.user_id = s.user_id
            WHERE u.email=%s AND u.role='student'
        """, (email,))
        user = cur.fetchone()

        if user and bcrypt.check_password_hash(user['password'], password):
            _clear_login_attempts(cur, email)
            conn.commit()
            conn.close()
            session.clear()
            session['temp_user'] = user['user_id']
            session['student_id'] = user['student_id']
            session['otp_role'] = 'student'

            plain_otp = str(random.randint(100000, 999999))
            hashed_otp = bcrypt.generate_password_hash(plain_otp).decode()

            conn = get_connection()
            cur = conn.cursor()
            cur.execute("DELETE FROM otp_verification WHERE user_id=%s", (user['user_id'],))
            cur.execute("""
                INSERT INTO otp_verification (user_id, otp, expires_at)
                VALUES (%s, %s, %s)
            """, (user['user_id'], hashed_otp, datetime.now() + timedelta(minutes=5)))
            conn.commit()
            conn.close()

            send_otp_email(user['email'], plain_otp)
            flash("OTP sent to your email", "info")
            return redirect(url_for('verify_otp'))

        # Failed login: record attempt + maybe lock.
        locked = _record_failed_login(cur, email)
        conn.commit()
        conn.close()
        if locked:
            flash("Too many failed attempts. Account locked for 15 minutes.", "danger")
        else:
            flash("Invalid credentials", "danger")

    return render_template('student/student_login.html')


# =============================================================
# STUDENT DASHBOARD
# =============================================================
@app.route('/student_dashboard')
def student_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('student_login'))
    
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    cur.execute("""
        SELECT s.student_id, s.dept_id, s.year_of_study
        FROM students s WHERE s.user_id=%s
    """, (session['user_id'],))
    student_data = cur.fetchone()

    if not student_data:
        conn.close()
        return render_template('student/student_dashboard.html', announcements=[])

    student_id = student_data['student_id']
    dept_id = student_data['dept_id']
    year_of_study = student_data['year_of_study']

    # Pull course_ids for course-targeted announcements.
    cur.execute("SELECT DISTINCT course_id FROM enrollments WHERE student_id=%s", (student_id,))
    course_ids = [r['course_id'] for r in cur.fetchall()]
    announcements = _announcements_for(
        cur, role='student', dept_id=dept_id,
        year_of_study=year_of_study, course_ids=course_ids,
    )
    
    # Get all enrollments with grades for CGPA calculation
    cur.execute("""
        SELECT e.semester, e.grade, c.credits
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        WHERE e.student_id = %s AND e.grade IS NOT NULL
        ORDER BY e.semester
    """, (student_id,))
    
    enrollments = cur.fetchall()
    conn.close()
    
    # Calculate semester-wise GPA and cumulative CGPA
    semester_data = {}
    for enrollment in enrollments:
        semester = enrollment['semester']
        grade = enrollment['grade']
        credits = enrollment['credits']
        
        # Convert grade to grade points
        try:
            grade_points = float(grade)
        except (ValueError, TypeError):
            grade_map = {
                'A': 10, 'A+': 10, 'B': 8, 'B+': 9,
                'C': 6, 'C+': 7, 'D': 4, 'D+': 5, 'F': 0
            }
            grade_points = grade_map.get(str(grade).upper(), 0)
        
        if semester not in semester_data:
            semester_data[semester] = {'total_points': 0, 'total_credits': 0}
        
        semester_data[semester]['total_points'] += grade_points * credits
        semester_data[semester]['total_credits'] += credits
    
    # Calculate GPA for each semester
    mini_graph_data = []
    cumulative_points = 0
    cumulative_credits = 0
    
    for semester in sorted(semester_data.keys()):
        total_points = semester_data[semester]['total_points']
        total_credits = semester_data[semester]['total_credits']
        gpa = round(total_points / total_credits, 2) if total_credits > 0 else 0
        mini_graph_data.append({'semester': semester, 'gpa': gpa})
        
        cumulative_points += total_points
        cumulative_credits += total_credits
    
    # Get last 4 semesters for mini graph
    mini_graph_data = mini_graph_data[-4:] if len(mini_graph_data) > 4 else mini_graph_data
    
    cumulative_cgpa = round(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else None
    
    return render_template(
        'student/student_dashboard.html',
        cumulative_cgpa=cumulative_cgpa,
        mini_graph_data=mini_graph_data,
        announcements=announcements,
    )


@app.route('/student_profile')
def student_profile():
    if 'user_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT u.name, u.email, u.profile_photo, s.roll_no, s.year_of_study, d.dept_name
        FROM users u
        JOIN students s ON u.user_id=s.user_id
        JOIN departments d ON s.dept_id=d.dept_id
        WHERE u.user_id=%s
    """, (session['user_id'],))
    student = cur.fetchone()
    conn.close()
    return render_template('student/student_profile.html', student=student)


@app.route('/student_courses')
def student_courses():
    if 'user_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.course_name, c.credits, e.semester, e.grade,
               cs.section_label,
               COALESCE(u.name, '— Unassigned —') AS faculty_name
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        JOIN students s ON e.student_id = s.student_id
        LEFT JOIN course_sections cs ON cs.section_id = e.section_id
        LEFT JOIN faculty f ON cs.faculty_id = f.faculty_id
        LEFT JOIN users u ON f.user_id = u.user_id
        WHERE s.user_id=%s
        ORDER BY e.semester, c.course_name
    """, (session['user_id'],))
    courses = cur.fetchall()
    conn.close()
    return render_template('student/student_courses.html', courses=courses)


@app.route('/student_requests')
def student_requests():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT req_id, category, description, status, created_at
        FROM swd_requests
        WHERE student_id=%s
        ORDER BY created_at DESC
    """, (session['student_id'],))
    requests = cur.fetchall()
    conn.close()
    return render_template('student/student_requests.html', requests=requests)


@app.route('/new_request', methods=['GET', 'POST'])
def new_request():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    if request.method == 'POST':
        form = NewSWDRequestForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            return render_template('student/new_request.html')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO swd_requests (student_id, category, description)
            VALUES (%s, %s, %s)
        """, (
            session['student_id'],
            form.category.data,
            form.description.data,
        ))
        conn.commit()
        conn.close()
        flash("Request submitted", "success")
        return redirect(url_for('student_requests'))

    return render_template('student/new_request.html')


# =============================================================
# GPA / ACADEMIC PROGRESS
# =============================================================
@app.route('/student_progress')
def student_progress():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    
    # Get all enrollments with grades
    cur.execute("""
        SELECT e.semester, e.grade, c.credits
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        WHERE e.student_id = %s AND e.grade IS NOT NULL
        ORDER BY e.semester
    """, (session['student_id'],))
    
    enrollments = cur.fetchall()
    conn.close()
    
    # Calculate GPA per semester
    semester_data = {}
    for enrollment in enrollments:
        semester = enrollment['semester']
        grade = enrollment['grade']
        credits = enrollment['credits']
        
        # Convert grade to grade points (handle both letter and numeric grades)
        try:
            # Try numeric grade first (0-10 scale)
            grade_points = float(grade)
        except (ValueError, TypeError):
            # Handle letter grades
            grade_map = {
                'A': 10, 'A+': 10,
                'B': 8, 'B+': 9,
                'C': 6, 'C+': 7,
                'D': 4, 'D+': 5,
                'F': 0
            }
            grade_points = grade_map.get(str(grade).upper(), 0)
        
        if semester not in semester_data:
            semester_data[semester] = {'total_points': 0, 'total_credits': 0}
        
        semester_data[semester]['total_points'] += grade_points * credits
        semester_data[semester]['total_credits'] += credits
    
    # Calculate GPA for each semester
    data = []
    cumulative_points = 0
    cumulative_credits = 0
    
    for semester in sorted(semester_data.keys()):
        total_points = semester_data[semester]['total_points']
        total_credits = semester_data[semester]['total_credits']
        gpa = round(total_points / total_credits, 2) if total_credits > 0 else 0
        data.append({'semester': semester, 'gpa': gpa})
        
        cumulative_points += total_points
        cumulative_credits += total_credits
    
    # Calculate cumulative CGPA
    cumulative_cgpa = round(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else 0
    
    return render_template('student/progress.html', data=data, cumulative_cgpa=cumulative_cgpa)


# =============================================================
# GRADE SIMULATOR
# =============================================================
@app.route('/grade_simulator')
def grade_simulator():
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # 1. Fetch ALL enrollments (graded and ungraded)
    cur.execute("""
        SELECT e.semester, e.grade, c.course_id, c.course_name, c.credits, s.current_semester
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        JOIN students s ON e.student_id = s.student_id
        WHERE e.student_id = %s AND e.semester = s.current_semester
        ORDER BY c.course_name
    """, (session['student_id'],))
    all_enrollments = cur.fetchall()
    conn.close()

    total_points = 0
    total_credits = 0
    grade_map = {
        'A': 10, 'A+': 10, 'B': 8, 'B+': 9,
        'C': 6, 'C+': 7, 'D': 4, 'D+': 5, 'F': 0
    }

    # Calculate Current Real CGPA
    for record in all_enrollments:
        if record['grade']:
            try:
                gp = float(record['grade'])
            except (ValueError, TypeError):
                gp = grade_map.get(str(record['grade']).upper(), 0)
            
            total_points += gp * record['credits']
            total_credits += record['credits']

    current_cgpa = round(total_points / total_credits, 2) if total_credits > 0 else 0.0

    return render_template('student/grade_simulator.html', 
                           current_cgpa=current_cgpa,
                           enrollments=all_enrollments)



# =============================================================
# ATTENDANCE (B1) — student side
# =============================================================
@app.route('/student_attendance')
def student_attendance():
    """Per-course attendance % for the logged-in student.

    Surfaces a warning when the percentage falls below the configured
    threshold (default 75%, configurable via ATTENDANCE_WARN_THRESHOLD env).
    Excused sessions ('X') aren't counted in either numerator or denominator.
    """
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    import os as _os
    threshold = float(_os.environ.get("ATTENDANCE_WARN_THRESHOLD", "75"))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.course_name, cs.section_label, cs.semester,
               SUM(CASE WHEN a.status = 'P' THEN 1 ELSE 0 END) AS present,
               SUM(CASE WHEN a.status = 'L' THEN 1 ELSE 0 END) AS late,
               SUM(CASE WHEN a.status = 'A' THEN 1 ELSE 0 END) AS absent,
               SUM(CASE WHEN a.status = 'X' THEN 1 ELSE 0 END) AS excused,
               COUNT(*) AS total
        FROM attendance a
        JOIN course_sections cs ON cs.section_id = a.section_id
        JOIN courses c ON c.course_id = cs.course_id
        WHERE a.student_id = %s
        GROUP BY a.section_id, c.course_name, cs.section_label, cs.semester
        ORDER BY cs.semester, c.course_name
    """, (session['student_id'],))
    raw = cur.fetchall()
    conn.close()

    rows = []
    for r in raw:
        countable = (r['total'] or 0) - (r['excused'] or 0)
        present_or_late = (r['present'] or 0) + (r['late'] or 0)
        pct = round(100 * present_or_late / countable, 1) if countable else None
        rows.append({**r, "pct": pct, "below_threshold": pct is not None and pct < threshold})

    return render_template(
        'student/attendance.html',
        rows=rows,
        threshold=threshold,
    )


# =============================================================
# COURSE MATERIALS (B4) — student side
# =============================================================
@app.route('/student_materials')
def student_materials():
    """List downloadable materials for every course the student is enrolled in."""
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.material_id, m.title, m.file_name, m.size_bytes, m.uploaded_at,
               c.course_name, u.name AS uploader
        FROM course_materials m
        JOIN courses c ON m.course_id = c.course_id
        JOIN users u ON m.uploaded_by = u.user_id
        WHERE m.course_id IN (
            SELECT DISTINCT e.course_id FROM enrollments e
            WHERE e.student_id = %s
        )
        ORDER BY c.course_name, m.uploaded_at DESC
    """, (session['student_id'],))
    materials = cur.fetchall()
    conn.close()

    # Group by course for nicer rendering.
    by_course: dict = {}
    for m in materials:
        by_course.setdefault(m['course_name'], []).append(m)
    return render_template('student/materials.html', by_course=by_course)


# =============================================================
# DATA EXPORT (C10) — student downloads everything we have on them
# =============================================================
@app.route('/student_export')
def student_export():
    """Bundle the student's profile + enrollments + grades + requests +
    attendance + notifications into a single JSON download.

    Useful for transfers and as a basic GDPR-style "right of access"
    export. CSV would be marginally easier to spreadsheet but loses the
    nesting; JSON is the better fit for nested per-course data.
    """
    if 'student_id' not in session:
        return redirect(url_for('student_login'))

    import json
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT u.user_id, u.name, u.email,
               s.student_id, s.roll_no, s.year_of_study, s.current_semester,
               d.dept_name
        FROM users u
        JOIN students s ON u.user_id = s.user_id
        JOIN departments d ON s.dept_id = d.dept_id
        WHERE s.student_id = %s
    """, (session['student_id'],))
    profile = cur.fetchone()

    cur.execute("""
        SELECT c.course_name, c.credits, e.semester, e.grade,
               cs.section_label,
               COALESCE(u.name, '') AS faculty_name
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        LEFT JOIN course_sections cs ON cs.section_id = e.section_id
        LEFT JOIN faculty f ON cs.faculty_id = f.faculty_id
        LEFT JOIN users u ON f.user_id = u.user_id
        WHERE e.student_id = %s
        ORDER BY e.semester, c.course_name
    """, (session['student_id'],))
    enrollments = cur.fetchall()

    cur.execute("""
        SELECT r.req_id, r.category, r.description, r.status, r.created_at
        FROM swd_requests r WHERE r.student_id=%s ORDER BY r.created_at DESC
    """, (session['student_id'],))
    requests_ = cur.fetchall()

    cur.execute("""
        SELECT a.session_date, a.status, c.course_name, cs.section_label
        FROM attendance a
        JOIN course_sections cs ON cs.section_id = a.section_id
        JOIN courses c ON c.course_id = cs.course_id
        WHERE a.student_id = %s
        ORDER BY a.session_date DESC
    """, (session['student_id'],))
    attendance_rows = cur.fetchall()

    cur.execute("""
        SELECT kind, message, created_at, read_at FROM notifications
        WHERE user_id = %s ORDER BY created_at DESC LIMIT 200
    """, (session['user_id'],))
    notifs = cur.fetchall()

    conn.close()

    payload = {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "profile": profile,
        "enrollments": enrollments,
        "requests": requests_,
        "attendance": attendance_rows,
        "notifications": notifs,
    }
    body = json.dumps(payload, default=str, indent=2)
    resp = Response(body, mimetype="application/json")
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=erp_data_{profile['roll_no']}.json"
    )
    return resp
