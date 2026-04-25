"""Faculty-facing routes: login, dashboard, course/student management.

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
from forms import (
    CourseForm,
    EnrollForm,
    GradeComponentForm,
    GradeForm,
    LoginForm,
)


# =============================================================
# FACULTY
# =============================================================
@app.route('/faculty_login', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def faculty_login():
    if request.method == 'POST':
        form = LoginForm(request.form)
        if not form.validate():
            flash("Please enter a valid email and password.", "danger")
            return render_template('faculty/faculty_login.html')
        email = form.email.data.strip()
        password = form.password.data

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT u.user_id, u.password, u.email, f.dept_id
            FROM users u
            JOIN faculty f ON u.user_id = f.user_id
            WHERE u.email=%s AND u.role='faculty'
        """, (email,))
        user = cur.fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
            session.clear()
            session['temp_user'] = user['user_id']
            session['dept_id'] = user['dept_id']
            session['otp_role'] = 'faculty'

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

        flash("Invalid credentials", "danger")

    return render_template('faculty/faculty_login.html')

@app.route('/faculty_dashboard')
def faculty_dashboard():
    if session.get('role') != 'faculty' or 'dept_id' not in session:
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Get faculty_id for current user
    cur.execute("SELECT faculty_id FROM faculty WHERE user_id=%s", (session['temp_user'] if 'temp_user' in session else session.get('user_id'),))
    faculty_data = cur.fetchone()
    faculty_id = faculty_data['faculty_id'] if faculty_data else None
    
    if faculty_id and 'faculty_id' not in session:
        session['faculty_id'] = faculty_id

    conn.close()

    return render_template('faculty/faculty_dashboard.html')


@app.route('/faculty_courses')
def faculty_courses():
    if session.get('role') != 'faculty' or 'dept_id' not in session:
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Courses by faculty department
    cur.execute("""
        SELECT course_id, course_name, credits, semester
        FROM courses
        WHERE dept_id=%s
    """, (session['dept_id'],))
    courses = cur.fetchall()

    conn.close()
    return render_template('faculty/faculty_courses.html', courses=courses)


@app.route('/faculty_requests')
def faculty_requests():
    if session.get('role') != 'faculty' or 'dept_id' not in session:
        return redirect(url_for('faculty_login'))

    if 'faculty_id' not in session:
         conn = get_connection()
         cur = conn.cursor(dictionary=True)
         cur.execute("SELECT faculty_id FROM faculty WHERE user_id=%s", (session.get('user_id'),))
         faculty_data = cur.fetchone()
         session['faculty_id'] = faculty_data['faculty_id'] if faculty_data else None
         conn.close()

    if not session.get('faculty_id'):
        flash("Faculty profile not found", "error")
        return redirect(url_for('faculty_dashboard'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # SWD Requests forwarded to this faculty
    cur.execute("""
        SELECT r.req_id, r.category, r.description, r.status, 
               s.roll_no, u.name as student_name
        FROM swd_requests r
        JOIN students s ON r.student_id=s.student_id
        JOIN users u ON s.user_id=u.user_id
        WHERE r.assigned_faculty_id=%s
        ORDER BY r.created_at DESC
    """, (session['faculty_id'],))
    requests = cur.fetchall()
    
    conn.close()
    return render_template('faculty/faculty_requests.html', requests=requests)


@app.route('/faculty_add_course', methods=['GET', 'POST'])
def faculty_add_course():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    if request.method == 'POST':
        form = CourseForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            return render_template('faculty/add_course.html')
        name = form.course_name.data.strip()
        credits = form.credits.data
        dept_id = session['dept_id']

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO courses (course_name, dept_id, credits)
            VALUES (%s, %s, %s)
        """, (name, dept_id, credits))
        new_course_id = cur.lastrowid
        _audit(
            cur,
            session['user_id'],
            f"Created course_id={new_course_id} ({name!r}) credits={credits} dept_id={dept_id}",
        )
        conn.commit()
        conn.close()

        flash("Course created successfully", "success")

    return render_template('faculty/add_course.html')

@app.route('/faculty_enroll', methods=['GET', 'POST'])
def faculty_enroll():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM courses WHERE dept_id=%s", (session['dept_id'],))
    courses = cur.fetchall()

    cur.execute("SELECT student_id, roll_no FROM students WHERE dept_id=%s", (session['dept_id'],))
    students = cur.fetchall()

    if request.method == 'POST':
        form = EnrollForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            conn.close()
            return render_template(
                'faculty/enroll_student.html',
                courses=courses,
                students=students,
            )
        try:
            cur.execute("""
                INSERT INTO enrollments (student_id, course_id, semester)
                VALUES (%s, %s, %s)
            """, (form.student_id.data, form.course_id.data, form.semester.data))
            _audit(
                cur,
                session['user_id'],
                f"Enrolled student_id={form.student_id.data} into course_id={form.course_id.data} sem={form.semester.data}",
            )
            conn.commit()
            flash("Student enrolled", "success")
        except Error as e:
            if e.errno == 1062:
                flash("Student already enrolled in this course for this semester", "danger")
            else:
                logger.exception("Error enrolling student")
                flash("Error enrolling student. Please try again.", "danger")

    conn.close()
    return render_template(
        'faculty/enroll_student.html',
        courses=courses,
        students=students
    )

@app.route('/faculty_edit_course/<int:course_id>', methods=['GET', 'POST'])
def faculty_edit_course(course_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)


    if request.method == 'POST':
        form = CourseForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
            conn.close()
            return redirect(url_for('faculty_edit_course', course_id=course_id))
        course_name = form.course_name.data.strip()
        credits = form.credits.data

        cur.execute("""
            UPDATE courses
            SET course_name=%s, credits=%s
            WHERE course_id=%s AND dept_id=%s
        """, (course_name, credits, course_id, session['dept_id']))
        _audit(
            cur,
            session['user_id'],
            f"Edited course_id={course_id} name={course_name!r} credits={credits}",
        )
        conn.commit()
        conn.close()
        
        flash("Course updated successfully", "success")
        return redirect(url_for('faculty_dashboard'))

    # GET request - fetch course data
    cur.execute("""
        SELECT course_id, course_name, credits, semester
        FROM courses
        WHERE course_id=%s AND dept_id=%s
    """, (course_id, session['dept_id']))
    course = cur.fetchone()
    conn.close()

    if not course:
        flash("Course not found or access denied", "danger")
        return redirect(url_for('faculty_dashboard'))

    return render_template('faculty/edit_course.html', course=course)

@app.route('/faculty_delete_course/<int:course_id>', methods=['POST'])
def faculty_delete_course(course_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Check if course has enrollments
    cur.execute("SELECT COUNT(*) as count FROM enrollments WHERE course_id=%s", (course_id,))
    result = cur.fetchone()
    
    if result['count'] > 0:
        flash("Cannot delete course with enrolled students", "danger")
        conn.close()
        return redirect(url_for('faculty_dashboard'))

    # Delete course
    cur.execute("DELETE FROM courses WHERE course_id=%s AND dept_id=%s", (course_id, session['dept_id']))
    _audit(cur, session['user_id'], f"Deleted course_id={course_id}")
    conn.commit()
    conn.close()

    flash("Course deleted successfully", "success")
    return redirect(url_for('faculty_dashboard'))

@app.route('/faculty_students')
def faculty_students():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Get all students in the department with their grades
    cur.execute("""
        SELECT s.student_id, s.roll_no, s.year_of_study,
               u.name, u.email
        FROM students s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.dept_id = %s
        ORDER BY s.year_of_study, u.name
    """, (session['dept_id'],))
    
    students = cur.fetchall()
    
    # Calculate cumulative CGPA for each student
    for student in students:
        cur.execute("""
            SELECT e.grade, c.credits
            FROM enrollments e
            JOIN courses c ON e.course_id = c.course_id
            WHERE e.student_id = %s AND e.grade IS NOT NULL
        """, (student['student_id'],))
        
        grades = cur.fetchall()
        
        total_points = 0
        total_credits = 0
        
        for grade_row in grades:
            grade = grade_row['grade']
            credits = grade_row['credits']
            
            # Convert grade to grade points
            try:
                grade_points = float(grade)
            except (ValueError, TypeError):
                grade_map = {
                    'A': 10, 'A+': 10, 'B': 8, 'B+': 9,
                    'C': 6, 'C+': 7, 'D': 4, 'D+': 5, 'F': 0
                }
                grade_points = grade_map.get(str(grade).upper(), 0)
            
            total_points += grade_points * credits
            total_credits += credits
        
        student['cgpa'] = round(total_points / total_credits, 2) if total_credits > 0 else None
    
    conn.close()
    
    # Group students by year
    students_by_year = {}
    for student in students:
        year = student['year_of_study']
        if year not in students_by_year:
            students_by_year[year] = []
        students_by_year[year].append(student)
    
    return render_template('faculty/students.html', students_by_year=students_by_year)

@app.route('/faculty_student_detail/<int:student_id>')
def faculty_student_detail(student_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Get student info
    cur.execute("""
        SELECT s.student_id, s.roll_no, s.year_of_study, s.dept_id,
               u.name, u.email
        FROM students s
        JOIN users u ON s.user_id = u.user_id
        WHERE s.student_id = %s AND s.dept_id = %s
    """, (student_id, session['dept_id']))
    
    student = cur.fetchone()
    
    if not student:
        flash("Student not found or access denied", "danger")
        conn.close()
        return redirect(url_for('faculty_students'))
    
    # Get all enrollments with grades
    cur.execute("""
        SELECT e.semester, e.grade, c.credits, c.course_name
        FROM enrollments e
        JOIN courses c ON e.course_id = c.course_id
        WHERE e.student_id = %s AND e.grade IS NOT NULL
        ORDER BY e.semester
    """, (student_id,))
    
    enrollments = cur.fetchall()
    conn.close()
    
    # Calculate semester-wise CGPA
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
    
    # Calculate GPA for each semester and cumulative
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
    
    cumulative_cgpa = round(cumulative_points / cumulative_credits, 2) if cumulative_credits > 0 else 0
    
    return render_template('faculty/student_detail.html', 
                         student=student, 
                         data=data, 
                         cumulative_cgpa=cumulative_cgpa)

@app.route('/faculty_grades/<int:enrollment_id>', methods=['GET', 'POST'])
def faculty_grades(enrollment_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if request.method == 'POST':
        form = GradeComponentForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
        else:
            component = form.component.data.strip()
            marks = form.marks.data
            cur.execute("""
                INSERT INTO grade_components (enrollment_id, component_name, marks)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE marks=%s
            """, (enrollment_id, component, marks, marks))
            _audit(
                cur,
                session['user_id'],
                f"Set grade component {component!r}={marks} for enrollment_id={enrollment_id}",
            )
            conn.commit()

    cur.execute("""
        SELECT component_name, marks
        FROM grade_components
        WHERE enrollment_id=%s
    """, (enrollment_id,))
    grades = cur.fetchall()

    conn.close()
    return render_template('faculty/grades.html', grades=grades)

@app.route('/update_request/<int:req_id>/<string:action>')
def update_request(req_id, action):
    if action not in ['approved', 'rejected']:
        return redirect(url_for('faculty_dashboard'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE swd_requests
        SET status=%s, resolved_by=%s
        WHERE req_id=%s
    """, (action, session['user_id'], req_id))

    _audit(cur, session['user_id'], f"{action} request {req_id}")

    conn.commit()
    conn.close()

    return redirect(url_for('faculty_dashboard'))

@app.route('/faculty/course/<int:course_id>', methods=['GET', 'POST'])
def faculty_course_students(course_id):
    if 'user_id' not in session:
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Handle grade update
    if request.method == 'POST':
        form = GradeForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
        else:
            enrollment_id = form.enrollment_id.data
            grade = form.grade.data

            cur.execute("""
                UPDATE enrollments
                SET grade=%s
                WHERE enrollment_id=%s
            """, (grade, enrollment_id))

            _audit(
                cur,
                session['user_id'],
                f"Updated grade for enrollment {enrollment_id} -> {grade}",
            )
            conn.commit()

    # Get course info
    cur.execute("""
        SELECT course_name
        FROM courses
        WHERE course_id=%s
    """, (course_id,))
    course = cur.fetchone()

    # Get enrolled students
    cur.execute("""
        SELECT e.enrollment_id, s.roll_no, u.name, e.grade
        FROM enrollments e
        JOIN students s ON e.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        WHERE e.course_id=%s
    """, (course_id,))
    students = cur.fetchall()

    conn.close()

    return render_template(
        'faculty/course_students.html',
        course=course,
        students=students
    )


# =============================================================
# ADMIN
