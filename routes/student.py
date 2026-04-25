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

from app import _audit, app, bcrypt, csrf, limiter, logger
from db import get_connection
from utils.email_utils import send_otp_email, send_password_reset_email
from forms import LoginForm


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
        cur.execute("""
            SELECT u.user_id, u.password, u.email, s.student_id
            FROM users u
            JOIN students s ON u.user_id = s.user_id
            WHERE u.email=%s AND u.role='student'
        """, (email,))
        user = cur.fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
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
    
    # Get student_id
    cur.execute("SELECT student_id FROM students WHERE user_id=%s", (session['user_id'],))
    student_data = cur.fetchone()
    
    if not student_data:
        conn.close()
        return render_template('student/student_dashboard.html')
    
    student_id = student_data['student_id']
    
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
    
    return render_template('student/student_dashboard.html', 
                         cumulative_cgpa=cumulative_cgpa,
                         mini_graph_data=mini_graph_data)


@app.route('/student_profile')
def student_profile():
    if 'user_id' not in session:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT u.name, u.email, s.roll_no, s.year_of_study, d.dept_name
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
        SELECT c.course_name, c.credits, e.semester, e.grade
        FROM enrollments e
        JOIN courses c ON e.course_id=c.course_id
        JOIN students s ON e.student_id=s.student_id
        WHERE s.user_id=%s
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
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO swd_requests (student_id, category, description)
            VALUES (%s, %s, %s)
        """, (
            session['student_id'],
            request.form['category'].strip(),
            request.form['description'].strip()
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
