from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_bcrypt import Bcrypt
from db import get_connection
import random
from datetime import date
from datetime import datetime, timedelta
from utils.email_utils import send_otp_email
import csv
import io
from flask import Response
import uuid
from mysql.connector import Error

app = Flask(__name__)
app.secret_key = "supersecretkey"

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

            print("RESET LINK (dev):",
                  f"http://127.0.0.1:5000/reset_password/{token}")

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
    return render_template('student/student_dashboard.html')


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
    cur.execute("""
        SELECT semester,
        ROUND(SUM(grade_points * credits)/SUM(credits),2) AS gpa
        FROM enrollments e
        JOIN courses c ON e.course_id=c.course_id
        WHERE student_id=%s
        GROUP BY semester
        ORDER BY semester
    """, (session['student_id'],))
    data = cur.fetchall()
    conn.close()
    return render_template('student/progress.html', data=data)


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

            print("FACULTY OTP (dev):", plain_otp)
            return redirect(url_for('verify_otp'))

        flash("Invalid credentials", "danger")

    return render_template('faculty/faculty_login.html')

@app.route('/faculty_dashboard')
def faculty_dashboard():
    if 'dept_id' not in session:
        return redirect(url_for('faculty_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # SWD Requests
    cur.execute("""
        SELECT r.req_id, r.category, r.description, r.status, s.roll_no
        FROM swd_requests r
        JOIN students s ON r.student_id=s.student_id
        WHERE s.dept_id=%s
    """, (session['dept_id'],))
    requests = cur.fetchall()

    # Courses by faculty department
    cur.execute("""
        SELECT course_id, course_name, credits
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

    conn.close()
    return render_template(
        'faculty/enroll_student.html',
        courses=courses,
        students=students
    )

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

            print("ADMIN OTP (dev):", plain_otp)
            return redirect(url_for('verify_otp'))

        flash("Invalid credentials", "danger")

    return render_template('admin/admin_login.html')


@app.route('/admin_dashboard')
def admin_dashboard():
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
        'admin/admin_dashboard.html',
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

# =============================================================
# LOGOUT
# =============================================================
@app.route('/logout')
def logout():
    session.clear()
    flash("Logged out", "info")
    return redirect(url_for('home'))


# =============================================================
# MAIN
# =============================================================
if __name__ == '__main__':
    app.run(debug=True)
