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

from app import _audit, app, bcrypt, csrf, limiter, logger
from db import get_connection
from utils.email_utils import send_otp_email, send_password_reset_email
from forms import LoginForm


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
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT a.action, a.created_at, a.ip_address, a.user_agent, u.email
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
                # Minimal required student fields
                cur.execute("""
                    INSERT INTO students (user_id, roll_no, dept_id, year_of_study, current_semester)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    user_id,
                    request.form['roll_no'],
                    request.form['dept_id'],
                    request.form['year_of_study'],
                    request.form['current_semester']
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






@app.route('/admin_manage_students')
def admin_manage_students():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    # Fetch all students with details
    cur.execute("""
        SELECT s.student_id, s.roll_no, s.year_of_study, s.current_semester, s.dept_id,
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

@app.route('/admin_update_semester/<int:student_id>', methods=['POST'])
def admin_update_semester(student_id):
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))
    
    new_semester = request.form.get('semester')
    
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE students
        SET current_semester = %s
        WHERE student_id = %s
    """, (new_semester, student_id))
    
    conn.commit()
    conn.close()
    
    flash(f"Student updated to Semester {new_semester}", "success")
    return redirect(url_for('admin_manage_students'))

@app.route('/admin_bulk_promote', methods=['POST'])
def admin_bulk_promote():
    if session.get('role') != 'admin':
        return redirect(url_for('admin_login'))

    from_sem = request.form.get('from_semester')
    to_sem = request.form.get('to_semester')

    if not from_sem or not to_sem:
        flash("Please select both semesters.", "danger")
        return redirect(url_for('admin_manage_students'))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE students
        SET current_semester = %s
        WHERE current_semester = %s
    """, (to_sem, from_sem))
    
    rows_affected = cur.rowcount
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
        current_sem = request.form['current_semester']
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
                SET roll_no=%s, year_of_study=%s, current_semester=%s, dept_id=%s 
                WHERE student_id=%s
            """, (roll_no, year, current_sem, dept_id, student_id))
            
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
