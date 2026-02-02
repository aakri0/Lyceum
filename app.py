from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_bcrypt import Bcrypt
from db import get_connection
import random
from datetime import date
from datetime import datetime, timedelta
from utils.email_utils import send_otp_email, send_password_reset_email
import csv
import io
from flask import Response
import uuid
from mysql.connector import Error

app = Flask(__name__, template_folder='frontend')
app.secret_key = "supersecretkey"

@app.template_filter('ordinal_year')
def ordinal_year_filter(year):
    if not year:
        return ""
    try:
        y = int(year)
        if y == 1: return "1st Year"
        if y == 2: return "2nd Year"
        if y == 3: return "3rd Year"
        return f"{y}th Year"
    except:
        return f"Year {year}"

bcrypt = Bcrypt(app)

# =============================================================
# HOME
# =============================================================
@app.route('/')
def home():
    return render_template('home.html')

# =============================================================
# STUDENT LOGIN + OTP
# =============================================================
@app.route('/student_login', methods=['GET', 'POST'])
def student_login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()

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


@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    if request.method == 'POST':
        otp = request.form['otp'].strip()
        user_id = session.get('temp_user')
        role = session.get('otp_role')

        if not user_id or not role:
            flash("Session expired. Please login again.", "warning")
            return redirect(url_for('home'))

        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # 🔐 Fetch hashed OTP (stored in `otp` column)
        cur.execute("""
            SELECT otp, expires_at
            FROM otp_verification
            WHERE user_id=%s AND expires_at > NOW()
        """, (user_id,))
        record = cur.fetchone()

        # ✅ SUCCESS: OTP matches hash
        if record and bcrypt.check_password_hash(record['otp'], otp):

            # 🔥 Delete OTP after successful verification
            cur.execute(
                "DELETE FROM otp_verification WHERE user_id=%s",
                (user_id,)
            )
            conn.commit()
            conn.close()

            # ✅ Finalize login
            session.pop('temp_user', None)
            session.pop('otp_role', None)
            session['user_id'] = user_id
            session['role'] = role

            # 🔁 Check force reset
            conn = get_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT force_reset, role FROM users WHERE user_id=%s",
                (user_id,)
            )
            user = cur.fetchone()
            conn.close()

            if user and user['force_reset']:
                return redirect(url_for('force_reset_password'))

            # 🚀 Redirect by role
            if user['role'] == 'student':
                return redirect(url_for('student_dashboard'))
            elif user['role'] == 'faculty':
                return redirect(url_for('faculty_dashboard'))
            elif user['role'] == 'admin':
                return redirect(url_for('admin_dashboard'))

        # ❌ FAILURE
        conn.close()
        flash("Invalid or expired OTP", "danger")

    return render_template('verify_otp.html')


@app.route('/resend_otp')
def resend_otp():
    user_id = session.get('temp_user')
    if not user_id:
        return redirect(url_for('student_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT email FROM users WHERE user_id=%s", (user_id,))
    user = cur.fetchone()

    plain_otp = str(random.randint(100000, 999999))
    hashed_otp = bcrypt.generate_password_hash(plain_otp).decode()
    cur.execute("DELETE FROM otp_verification WHERE user_id=%s", (user_id,))
    cur.execute("""
        INSERT INTO otp_verification (user_id, otp, expires_at)
        VALUES (%s, %s, NOW() + INTERVAL 5 MINUTE)
    """, (user_id, hashed_otp))

    conn.commit()
    conn.close()

    send_otp_email(user['email'], plain_otp)
    flash("OTP resent", "info")
    return redirect(url_for('verify_otp'))

@app.route('/force_reset_password', methods=['GET', 'POST'])
def force_reset_password():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        pwd = request.form['password']
        confirm = request.form['confirm']

        if pwd != confirm:
            flash("Passwords do not match", "danger")
            return redirect(url_for('force_reset_password'))

        hashed = bcrypt.generate_password_hash(pwd).decode()

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
            SET password=%s, force_reset=0
            WHERE user_id=%s
        """, (hashed, session['user_id']))
        conn.commit()
        conn.close()

        flash("Password updated successfully", "success")
        return redirect(url_for('home'))

    return render_template('force_reset_password.html')
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT user_id FROM users WHERE email=%s", (email,))
        user = cur.fetchone()

        if user:
            token = str(uuid.uuid4())
            cur.execute("DELETE FROM password_resets WHERE user_id=%s", (user['user_id'],))
            cur.execute("""
                INSERT INTO password_resets (user_id, token, expires_at)
                VALUES (%s, %s, NOW() + INTERVAL 15 MINUTE)
            """, (user['user_id'], token))
            conn.commit()

            reset_link = f"http://127.0.0.1:5000/reset_password/{token}"
            send_password_reset_email(email, reset_link)

        conn.close()
        flash("If email exists, reset link has been sent", "info")
        return redirect(url_for('home'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT user_id FROM password_resets
        WHERE token=%s AND expires_at > NOW()
    """, (token,))
    record = cur.fetchone()

    if not record:
        conn.close()
        flash("Invalid or expired link", "danger")
        return redirect(url_for('home'))

    if request.method == 'POST':
        pwd = request.form['password']
        confirm = request.form['confirm']

        if pwd != confirm:
            flash("Passwords do not match", "danger")
            return redirect(request.url)

        hashed = bcrypt.generate_password_hash(pwd).decode()
        cur.execute("""
            UPDATE users SET password=%s WHERE user_id=%s
        """, (hashed, record['user_id']))
        cur.execute("DELETE FROM password_resets WHERE user_id=%s", (record['user_id'],))
        conn.commit()
        conn.close()

        flash("Password reset successful", "success")
        return redirect(url_for('home'))

    conn.close()
    return render_template('reset_password.html')


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
# FACULTY
# =============================================================
@app.route('/faculty_login', methods=['GET', 'POST'])
def faculty_login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()

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
    if 'dept_id' not in session:
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Get faculty_id for current user
    cur.execute("SELECT faculty_id FROM faculty WHERE user_id=%s", (session['temp_user'] if 'temp_user' in session else session.get('user_id'),))
    faculty_data = cur.fetchone()
    faculty_id = faculty_data['faculty_id'] if faculty_data else None
    
    if faculty_id and 'faculty_id' not in session:
        session['faculty_id'] = faculty_id

    # SWD Requests forwarded to this faculty
    cur.execute("""
        SELECT r.req_id, r.category, r.description, r.status, 
               s.roll_no, u.name as student_name
        FROM swd_requests r
        JOIN students s ON r.student_id=s.student_id
        JOIN users u ON s.user_id=u.user_id
        WHERE r.assigned_faculty_id=%s
        ORDER BY r.created_at DESC
    """, (faculty_id,))
    requests = cur.fetchall()

    # Courses by faculty department
    cur.execute("""
        SELECT course_id, course_name, credits, semester
        FROM courses
        WHERE dept_id=%s
    """, (session['dept_id'],))
    courses = cur.fetchall()

    conn.close()

    return render_template(
        'faculty/faculty_dashboard.html',
        requests=requests,
        courses=courses
    )


@app.route('/faculty_add_course', methods=['GET', 'POST'])
def faculty_add_course():
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    if request.method == 'POST':
        name = request.form['course_name']
        credits = request.form['credits']
        dept_id = session['dept_id']

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO courses (course_name, dept_id, credits)
            VALUES (%s, %s, %s)
        """, (name, dept_id, credits))
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
        try:
            cur.execute("""
                INSERT INTO enrollments (student_id, course_id, semester)
                VALUES (%s, %s, %s)
            """, (
                request.form['student_id'],
                request.form['course_id'],
                request.form['semester']
            ))
            conn.commit()
            flash("Student enrolled", "success")
        except Error as e:
            if e.errno == 1062:
                flash("Student already enrolled in this course for this semester", "danger")
            else:
                flash(f"Error enrolling student: {e}", "danger")

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
        course_name = request.form['course_name']
        credits = request.form['credits']

        cur.execute("""
            UPDATE courses
            SET course_name=%s, credits=%s
            WHERE course_id=%s AND dept_id=%s
        """, (course_name, credits, course_id, session['dept_id']))
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
        component = request.form['component']
        marks = request.form['marks']

        cur.execute("""
            INSERT INTO grade_components (enrollment_id, component_name, marks)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE marks=%s
        """, (enrollment_id, component, marks, marks))
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

    cur.execute("""
        INSERT INTO audit_logs (user_id, action)
        VALUES (%s, %s)
    """, (session['user_id'], f"{action} request {req_id}"))

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
        enrollment_id = request.form['enrollment_id']
        grade = request.form['grade']

        cur.execute("""
            UPDATE enrollments
            SET grade=%s
            WHERE enrollment_id=%s
        """, (grade, enrollment_id))

        cur.execute("""
            INSERT INTO audit_logs (user_id, action)
            VALUES (%s, %s)
        """, (session['user_id'], f"Updated grade for enrollment {enrollment_id}"))

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
# =============================================================
@app.route('/admin_login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()

        conn = get_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT user_id, password, email
            FROM users
            WHERE email=%s AND role='admin'
        """, (email,))
        user = cur.fetchone()
        conn.close()

        if user and bcrypt.check_password_hash(user['password'], password):
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
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT a.action, a.created_at, u.email
        FROM audit_logs a
        JOIN users u ON a.user_id=u.user_id
        ORDER BY a.created_at DESC
    """)
    logs = cur.fetchall()
    conn.close()

    return render_template('admin/audit_logs.html', logs=logs)

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
        name = request.form['name'].strip()
        email = request.form['email'].strip()
        role = request.form['role']

        conn = get_connection()
        cur = conn.cursor(dictionary=True)

        # 🔒 Check duplicate email
        cur.execute("SELECT user_id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            conn.close()
            flash("User with this email already exists.", "danger")
            return redirect(url_for('admin_create_user'))

        hashed = bcrypt.generate_password_hash("test123").decode()

        try:
            # 1️⃣ Insert into users
            cur.execute("""
                INSERT INTO users (name, email, password, role, force_reset)
                VALUES (%s, %s, %s, %s, 1)
            """, (name, email, hashed, role))

            user_id = cur.lastrowid

            # 2️⃣ Insert role-specific data
            if role == 'student':
                # Minimal required student fields
                cur.execute("""
                    INSERT INTO students (user_id, roll_no, dept_id, year_of_study)
                    VALUES (%s, %s, %s, %s)
                """, (
                    user_id,
                    request.form['roll_no'],
                    request.form['dept_id'],
                    request.form['year_of_study']
                ))

            elif role == 'faculty':
                cur.execute("""
                    INSERT INTO faculty (user_id, dept_id)
                    VALUES (%s, %s)
                """, (
                    user_id,
                    request.form['dept_id']
                ))

            conn.commit()
            flash("User created successfully. Default password is test123.", "success")

        except Error as e:
            conn.rollback()
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

    action = request.form.get('action')  # 'approved', 'rejected', or 'pending'
    
    if action not in ['approved', 'rejected', 'pending']:
        flash("Invalid action", "danger")
        return redirect(url_for('admin_requests'))

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
    
    conn.commit()
    conn.close()

    flash(f"Request {action} successfully", "success")
    return redirect(url_for('admin_requests'))

@app.route('/admin_forward_request/<int:req_id>', methods=['POST'])
def admin_forward_request(req_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    faculty_id = request.form.get('faculty_id')
    
    if not faculty_id:
        flash("Please select a faculty member", "danger")
        return redirect(url_for('admin_requests'))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE swd_requests
        SET assigned_faculty_id = %s
        WHERE req_id = %s
    """, (faculty_id, req_id))
    conn.commit()
    conn.close()

    flash("Request forwarded to faculty successfully", "success")
    return redirect(url_for('admin_requests'))

# =============================================================
# LOGOUT
# =============================================================
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for('home'))



@app.route('/admin_manage_students')
def admin_manage_students():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Fetch all students with details
    cur.execute("""
        SELECT s.student_id, s.roll_no, s.year_of_study, s.dept_id,
               u.name, u.email, d.dept_name
        FROM students s
        JOIN users u ON s.user_id = u.user_id
        JOIN departments d ON s.dept_id = d.dept_id
        ORDER BY d.dept_name, s.year_of_study, s.roll_no
    """)
    students = cur.fetchall()
    conn.close()

    # Structure data: { 'Dept A': { 1: [students], 2: [students] } }
    structured_data = {}
    for student in students:
        dept = student['dept_name']
        year = student['year_of_study']
        
        if dept not in structured_data:
            structured_data[dept] = {}
        
        if year not in structured_data[dept]:
            structured_data[dept][year] = []
            
        structured_data[dept][year].append(student)

    return render_template('admin/manage_students.html', structured_data=structured_data)

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
        name = request.form['name']
        email = request.form['email']
        roll_no = request.form['roll_no']
        year = request.form['year_of_study']
        dept_id = request.form['dept_id']
        
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
                SET roll_no=%s, year_of_study=%s, dept_id=%s 
                WHERE student_id=%s
            """, (roll_no, year, dept_id, student_id))
            
            conn.commit()
            flash("Student updated successfully", "success")
            conn.close()
            return redirect(url_for('admin_manage_students'))
            
    # GET: Fetch student data and departments
    cur.execute("""
        SELECT s.student_id, s.roll_no, s.year_of_study, s.dept_id,
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

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT f.faculty_id, f.dept_id,
               u.name, u.email, d.dept_name
        FROM faculty f
        JOIN users u ON f.user_id = u.user_id
        JOIN departments d ON f.dept_id = d.dept_id
        ORDER BY d.dept_name, u.name
    """)
    faculty_list = cur.fetchall()
    conn.close()

    # Structure data: { 'Dept A': [faculty, ...], ... }
    structured_data = {}
    for f in faculty_list:
        dept = f['dept_name']
        if dept not in structured_data:
            structured_data[dept] = []
        structured_data[dept].append(f)

    return render_template('admin/manage_faculty.html', structured_data=structured_data)

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
        name = request.form['name']
        email = request.form['email']
        dept_id = request.form['dept_id']
        
        cur.execute("SELECT user_id FROM faculty WHERE faculty_id=%s", (faculty_id,))
        res = cur.fetchone()
        if res:
            user_id = res['user_id']
            cur.execute("UPDATE users SET name=%s, email=%s WHERE user_id=%s", (name, email, user_id))
            cur.execute("UPDATE faculty SET dept_id=%s WHERE faculty_id=%s", (dept_id, faculty_id))
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
        
    dept_name = request.form['dept_name']
    
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO departments (dept_name) VALUES (%s)", (dept_name,))
        conn.commit()
        flash("Department added successfully", "success")
    except Exception as e:
        flash(f"Error adding department: {e}", "danger")
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
        dept_name = request.form['dept_name']
        cur.execute("UPDATE departments SET dept_name=%s WHERE dept_id=%s", (dept_name, dept_id))
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
        conn.commit()
        flash("Department deleted successfully", "success")
    except Exception as e:
        # Constraint error likely if students/faculty exist
        flash("Cannot delete department. It may be linked to existing students or faculty.", "danger")
    finally:
        conn.close()
        
    return redirect(url_for('admin_manage_departments'))


# =============================================================
# MAIN
# =============================================================
if __name__ == '__main__':
    app.run(debug=True)
