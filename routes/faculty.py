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

from app import (
    _announcements_for,
    _audit,
    _clear_login_attempts,
    _is_locked,
    _notify,
    _record_failed_login,
    app,
    bcrypt,
    csrf,
    limiter,
    logger,
)
from db import get_connection
from utils.email_utils import send_otp_email, send_password_reset_email
from forms import (
    CourseForm,
    EnrollForm,
    GradeComponentForm,
    GradeForm,
    LoginForm,
)


def _faculty_teaches_course(cur, faculty_id, course_id) -> bool:
    """True iff faculty_id is allotted to ANY section of course_id.

    Used as the access check for faculty_edit_course / faculty_delete_course
    / faculty_grades / faculty_course_students. Replaces the old "course's
    dept_id == my dept_id" check, which let any faculty in the dept touch
    any course.
    """
    cur.execute(
        "SELECT 1 FROM course_sections WHERE faculty_id=%s AND course_id=%s LIMIT 1",
        (faculty_id, course_id),
    )
    return cur.fetchone() is not None


def _faculty_owns_section(cur, faculty_id, section_id) -> bool:
    """True iff this faculty is the owner of section_id."""
    cur.execute(
        "SELECT 1 FROM course_sections WHERE section_id=%s AND faculty_id=%s LIMIT 1",
        (section_id, faculty_id),
    )
    return cur.fetchone() is not None


def _faculty_owns_enrollment(cur, faculty_id, enrollment_id) -> bool:
    """True iff this faculty owns the section the enrollment belongs to."""
    cur.execute(
        """SELECT 1 FROM enrollments e
           JOIN course_sections cs ON cs.section_id = e.section_id
           WHERE e.enrollment_id=%s AND cs.faculty_id=%s LIMIT 1""",
        (enrollment_id, faculty_id),
    )
    return cur.fetchone() is not None


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

        if _is_locked(cur, email):
            conn.close()
            flash("Account temporarily locked due to too many failed attempts. "
                  "Try again later or use Forgot Password.", "danger")
            return render_template('faculty/faculty_login.html')

        cur.execute("""
            SELECT u.user_id, u.password, u.email, f.dept_id, f.faculty_id
            FROM users u
            JOIN faculty f ON u.user_id = f.user_id
            WHERE u.email=%s AND u.role='faculty'
        """, (email,))
        user = cur.fetchone()

        if user and bcrypt.check_password_hash(user['password'], password):
            _clear_login_attempts(cur, email)
            conn.commit()
            conn.close()
            session.clear()
            session['temp_user'] = user['user_id']
            session['dept_id'] = user['dept_id']
            session['faculty_id'] = user['faculty_id']
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

        locked = _record_failed_login(cur, email)
        conn.commit()
        conn.close()
        if locked:
            flash("Too many failed attempts. Account locked for 15 minutes.", "danger")
        else:
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

    # Pull announcements visible to this faculty (course-scoped via the
    # courses they teach via sections).
    cur.execute(
        "SELECT DISTINCT course_id FROM course_sections WHERE faculty_id=%s",
        (faculty_id,),
    )
    course_ids = [r['course_id'] for r in cur.fetchall()]
    announcements = _announcements_for(
        cur, role='faculty', dept_id=session.get('dept_id'),
        course_ids=course_ids,
    )

    # KPIs.
    cur.execute(
        "SELECT COUNT(*) AS c FROM course_sections WHERE faculty_id=%s",
        (faculty_id,),
    )
    section_count = cur.fetchone()['c']
    cur.execute("""
        SELECT COUNT(*) AS c FROM enrollments e
        JOIN course_sections cs ON cs.section_id = e.section_id
        WHERE cs.faculty_id = %s
    """, (faculty_id,))
    student_count = cur.fetchone()['c']
    cur.execute("""
        SELECT COUNT(*) AS c FROM swd_requests
        WHERE assigned_faculty_id=%s AND status='pending'
    """, (faculty_id,))
    pending_requests = cur.fetchone()['c']

    conn.close()

    return render_template(
        'faculty/faculty_dashboard.html',
        announcements=announcements,
        section_count=section_count,
        student_count=student_count,
        pending_requests=pending_requests,
    )


@app.route('/faculty_courses')
def faculty_courses():
    """Show only the sections this faculty member has been allotted.

    Each row is one section (course × label × semester). Faculty can have
    several sections of the same course or sections of different courses.
    """
    if session.get('role') != 'faculty' or 'dept_id' not in session:
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    if not faculty_id:
        flash("Your faculty profile is incomplete. Contact admin.", "warning")
        return redirect(url_for('faculty_dashboard'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT cs.section_id, cs.section_label, cs.semester, cs.capacity,
               c.course_id, c.course_name, c.credits,
               (SELECT COUNT(*) FROM enrollments e WHERE e.section_id = cs.section_id) AS enrolled_count
        FROM course_sections cs
        JOIN courses c ON c.course_id = cs.course_id
        WHERE cs.faculty_id = %s
        ORDER BY cs.semester, c.course_name, cs.section_label
    """, (faculty_id,))
    sections = cur.fetchall()
    conn.close()
    return render_template('faculty/faculty_courses.html', sections=sections)


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
    """Faculty enrolls a student into one of *their* sections.

    Section dropdown is restricted to sections this faculty member is
    allotted to — they can't roster a student into a section they don't
    teach. Capacity (if set on the section) is honoured.
    """
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    if not faculty_id:
        flash("Your faculty profile is incomplete. Contact admin.", "warning")
        return redirect(url_for('faculty_dashboard'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT cs.section_id, cs.section_label, cs.semester, cs.capacity,
               c.course_name, c.course_id,
               (SELECT COUNT(*) FROM enrollments e WHERE e.section_id = cs.section_id) AS enrolled_count
        FROM course_sections cs
        JOIN courses c ON c.course_id = cs.course_id
        WHERE cs.faculty_id = %s
        ORDER BY cs.semester, c.course_name, cs.section_label
    """, (faculty_id,))
    sections = cur.fetchall()

    cur.execute(
        "SELECT student_id, roll_no FROM students WHERE dept_id=%s ORDER BY roll_no",
        (session['dept_id'],),
    )
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
                sections=sections,
                students=students,
            )

        # Verify the picked section actually belongs to this faculty.
        cur.execute("""
            SELECT cs.section_id, cs.course_id, cs.semester, cs.capacity,
                   (SELECT COUNT(*) FROM enrollments e WHERE e.section_id = cs.section_id) AS enrolled
            FROM course_sections cs
            WHERE cs.section_id = %s AND cs.faculty_id = %s
        """, (form.section_id.data, faculty_id))
        section = cur.fetchone()
        if not section:
            conn.close()
            flash("That section is not allotted to you.", "danger")
            return redirect(url_for('faculty_enroll'))

        if section["capacity"] and section["enrolled"] >= section["capacity"]:
            conn.close()
            flash("Section is at full capacity.", "danger")
            return redirect(url_for('faculty_enroll'))

        try:
            cur.execute("""
                INSERT INTO enrollments (student_id, course_id, section_id, semester)
                VALUES (%s, %s, %s, %s)
            """, (
                form.student_id.data,
                section["course_id"],
                section["section_id"],
                section["semester"],
            ))
            _audit(
                cur,
                session['user_id'],
                f"Enrolled student_id={form.student_id.data} into section_id={section['section_id']} (course_id={section['course_id']} sem={section['semester']})",
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
        sections=sections,
        students=students,
    )

@app.route('/faculty_edit_course/<int:course_id>', methods=['GET', 'POST'])
def faculty_edit_course(course_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_teaches_course(cur, faculty_id, course_id):
        conn.close()
        flash("You can only edit courses you're allotted to.", "danger")
        return redirect(url_for('faculty_courses'))

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
            WHERE course_id=%s
        """, (course_name, credits, course_id))
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
        WHERE course_id=%s
    """, (course_id,))
    course = cur.fetchone()
    conn.close()

    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for('faculty_courses'))

    return render_template('faculty/edit_course.html', course=course)

@app.route('/faculty_delete_course/<int:course_id>', methods=['POST'])
def faculty_delete_course(course_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_teaches_course(cur, faculty_id, course_id):
        conn.close()
        flash("You can only delete courses you're allotted to.", "danger")
        return redirect(url_for('faculty_courses'))

    # Check if course has enrollments
    cur.execute("SELECT COUNT(*) as count FROM enrollments WHERE course_id=%s", (course_id,))
    result = cur.fetchone()

    if result['count'] > 0:
        flash("Cannot delete course with enrolled students", "danger")
        conn.close()
        return redirect(url_for('faculty_courses'))

    cur.execute("DELETE FROM courses WHERE course_id=%s", (course_id,))
    _audit(cur, session['user_id'], f"Deleted course_id={course_id}")
    conn.commit()
    conn.close()

    flash("Course deleted successfully", "success")
    return redirect(url_for('faculty_courses'))

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

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_owns_enrollment(cur, faculty_id, enrollment_id):
        conn.close()
        flash("You don't teach the section this enrollment belongs to.", "danger")
        return redirect(url_for('faculty_courses'))

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
    """Roster + grade entry for *only* the sections of this course that
    the current faculty member is allotted to. If they teach multiple
    sections of the same course, all sections' rosters are shown grouped.
    """
    if 'user_id' not in session:
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_teaches_course(cur, faculty_id, course_id):
        conn.close()
        flash("You're not allotted to any section of this course.", "danger")
        return redirect(url_for('faculty_courses'))

    # Handle grade update — verify the enrollment belongs to a section we own.
    if request.method == 'POST':
        form = GradeForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(f"{field}: {err}", "danger")
        elif not _faculty_owns_enrollment(cur, faculty_id, form.enrollment_id.data):
            flash("Cannot grade a student outside your sections.", "danger")
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

            # Notify the student whose grade was posted.
            cur.execute("""
                SELECT u.user_id, c.course_name
                FROM enrollments e
                JOIN students s ON e.student_id = s.student_id
                JOIN users u ON s.user_id = u.user_id
                JOIN courses c ON e.course_id = c.course_id
                WHERE e.enrollment_id = %s
            """, (enrollment_id,))
            row = cur.fetchone()
            if row:
                _notify(
                    cur, row['user_id'], 'grade_posted',
                    f"Your grade for {row['course_name']} is {grade}.",
                    url_for('student_courses'),
                )
            conn.commit()

    cur.execute("""
        SELECT course_name
        FROM courses
        WHERE course_id=%s
    """, (course_id,))
    course = cur.fetchone()

    cur.execute("""
        SELECT e.enrollment_id, s.roll_no, u.name, e.grade,
               cs.section_label, cs.semester
        FROM enrollments e
        JOIN course_sections cs ON cs.section_id = e.section_id
        JOIN students s ON e.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        WHERE e.course_id = %s AND cs.faculty_id = %s
        ORDER BY cs.section_label, s.roll_no
    """, (course_id, faculty_id))
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
# ATTENDANCE (B1) — faculty side
# =============================================================
@app.route('/faculty_attendance/<int:section_id>', methods=['GET', 'POST'])
def faculty_attendance(section_id):
    """Mark attendance for a section on a given date.

    GET: form showing every enrolled student with present/absent radio.
    POST: upserts (section_id, student_id, session_date, status) per row.

    Pre-fills with whatever was already marked for that date so faculty
    can correct mistakes the same day.
    """
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_owns_section(cur, faculty_id, section_id):
        conn.close()
        flash("That section is not allotted to you.", "danger")
        return redirect(url_for('faculty_courses'))

    # Date defaults to today; faculty can back-mark via ?date=YYYY-MM-DD
    raw_date = request.values.get('date') or date.today().isoformat()
    try:
        session_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Invalid date format.", "danger")
        return redirect(url_for('faculty_attendance', section_id=section_id))

    if session_date > date.today():
        conn.close()
        flash("Cannot mark attendance for a future date.", "danger")
        return redirect(url_for('faculty_attendance', section_id=section_id))

    if request.method == 'POST':
        # Form sends a status per student: status_<student_id>=P|A|L|X
        cur.execute("""
            SELECT s.student_id FROM enrollments e
            JOIN students s ON e.student_id = s.student_id
            WHERE e.section_id = %s
        """, (section_id,))
        student_ids = [row['student_id'] for row in cur.fetchall()]
        marked = 0
        for sid in student_ids:
            status = request.form.get(f'status_{sid}', 'A').upper()
            if status not in ('P', 'A', 'L', 'X'):
                continue
            cur.execute("""
                INSERT INTO attendance (section_id, student_id, session_date, status, marked_by)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE status=VALUES(status), marked_by=VALUES(marked_by), marked_at=CURRENT_TIMESTAMP
            """, (section_id, sid, session_date, status, session['user_id']))
            marked += 1
        _audit(
            cur,
            session['user_id'],
            f"Marked attendance for section_id={section_id} date={session_date} ({marked} rows)",
        )
        conn.commit()
        flash(f"Attendance saved for {marked} students on {session_date}.", "success")
        return redirect(url_for('faculty_attendance', section_id=section_id, date=raw_date))

    # GET — load roster + any existing marks for this date.
    cur.execute("""
        SELECT s.student_id, s.roll_no, u.name,
               (SELECT a.status FROM attendance a
                 WHERE a.section_id=%s AND a.student_id=s.student_id AND a.session_date=%s
                 LIMIT 1) AS marked_status
        FROM enrollments e
        JOIN students s ON e.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        WHERE e.section_id = %s
        ORDER BY s.roll_no
    """, (section_id, session_date, section_id))
    roster = cur.fetchall()

    cur.execute("""
        SELECT cs.section_label, cs.semester, c.course_name
        FROM course_sections cs JOIN courses c ON c.course_id = cs.course_id
        WHERE cs.section_id = %s
    """, (section_id,))
    section = cur.fetchone()

    conn.close()
    return render_template(
        'faculty/attendance.html',
        section=section,
        section_id=section_id,
        roster=roster,
        session_date=session_date,
    )


# =============================================================
# COURSE MATERIALS (B4) — faculty upload, students download
# =============================================================
import mimetypes
import os
import uuid as _uuid
from pathlib import Path

from flask import abort, send_from_directory
from werkzeug.utils import secure_filename

ALLOWED_MIME_PREFIXES = ("application/pdf", "image/", "text/")
ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".txt", ".md", ".csv",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".zip",
}


def _upload_dir() -> Path:
    p = Path(os.environ.get("UPLOAD_DIR", "./uploads")).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _max_upload_bytes() -> int:
    return int(os.environ.get("MAX_UPLOAD_MB", "20")) * 1024 * 1024


@app.route('/faculty_materials/<int:course_id>', methods=['GET', 'POST'])
def faculty_materials(course_id):
    """Faculty uploads / lists materials for a course they teach.

    Files are written to UPLOAD_DIR with a UUID-prefixed name so concurrent
    uploads of the same filename don't collide. Original name is preserved
    in the DB row for download display.
    """
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_teaches_course(cur, faculty_id, course_id):
        conn.close()
        flash("You're not allotted to this course.", "danger")
        return redirect(url_for('faculty_courses'))

    if request.method == 'POST':
        title = (request.form.get('title') or '').strip()[:200]
        f = request.files.get('material_file')
        if not title or not f or not f.filename:
            flash("Title and a file are required.", "danger")
            return redirect(url_for('faculty_materials', course_id=course_id))

        safe_name = secure_filename(f.filename)
        if not safe_name:
            flash("Invalid filename.", "danger")
            return redirect(url_for('faculty_materials', course_id=course_id))

        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            flash(f"File type {ext} is not allowed.", "danger")
            return redirect(url_for('faculty_materials', course_id=course_id))

        guessed_mime = (f.mimetype or mimetypes.guess_type(safe_name)[0] or "application/octet-stream")
        if not any(guessed_mime.startswith(p) for p in ALLOWED_MIME_PREFIXES) \
                and guessed_mime not in {
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/vnd.ms-powerpoint",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/zip",
                }:
            flash(f"MIME type {guessed_mime} is not allowed.", "danger")
            return redirect(url_for('faculty_materials', course_id=course_id))

        # Stream-to-disk and check size.
        unique = f"{_uuid.uuid4().hex}_{safe_name}"
        dest = _upload_dir() / unique
        size = 0
        max_bytes = _max_upload_bytes()
        with dest.open("wb") as out:
            while True:
                chunk = f.stream.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    conn.close()
                    flash(f"File exceeds the {max_bytes // (1024*1024)} MB limit.", "danger")
                    return redirect(url_for('faculty_materials', course_id=course_id))
                out.write(chunk)

        cur.execute("""
            INSERT INTO course_materials
              (course_id, uploaded_by, title, file_name, file_path, mime_type, size_bytes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (course_id, session['user_id'], title, safe_name, unique, guessed_mime, size))
        new_id = cur.lastrowid
        _audit(
            cur, session['user_id'],
            f"Uploaded material_id={new_id} ({safe_name}, {size}B) to course_id={course_id}",
        )
        conn.commit()
        flash("Material uploaded.", "success")
        return redirect(url_for('faculty_materials', course_id=course_id))

    cur.execute("""
        SELECT m.material_id, m.title, m.file_name, m.size_bytes, m.uploaded_at,
               u.name AS uploader
        FROM course_materials m
        JOIN users u ON m.uploaded_by = u.user_id
        WHERE m.course_id = %s
        ORDER BY m.uploaded_at DESC
    """, (course_id,))
    materials = cur.fetchall()

    cur.execute("SELECT course_name FROM courses WHERE course_id=%s", (course_id,))
    course = cur.fetchone()
    conn.close()
    return render_template(
        'faculty/materials.html',
        course=course, course_id=course_id, materials=materials,
        max_mb=int(os.environ.get("MAX_UPLOAD_MB", "20")),
    )


@app.route('/faculty_material_delete/<int:material_id>', methods=['POST'])
def faculty_material_delete(material_id):
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))
    faculty_id = session.get('faculty_id')

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.course_id, m.file_path
        FROM course_materials m WHERE m.material_id=%s
    """, (material_id,))
    row = cur.fetchone()
    if not row or not _faculty_teaches_course(cur, faculty_id, row['course_id']):
        conn.close()
        flash("Not allowed.", "danger")
        return redirect(url_for('faculty_courses'))

    cur.execute("DELETE FROM course_materials WHERE material_id=%s", (material_id,))
    _audit(cur, session['user_id'], f"Deleted material_id={material_id}")
    conn.commit()
    conn.close()
    try:
        (_upload_dir() / row['file_path']).unlink(missing_ok=True)
    except Exception:
        logger.exception("orphan upload cleanup failed")
    flash("Material deleted.", "success")
    return redirect(url_for('faculty_materials', course_id=row['course_id']))


@app.route('/material/<int:material_id>')
def download_material(material_id):
    """Download a course material — gated to enrolled students + course faculty."""
    if not session.get('user_id'):
        return redirect(url_for('home'))

    conn = get_connection()
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT m.course_id, m.file_name, m.file_path, m.mime_type
        FROM course_materials m WHERE m.material_id=%s
    """, (material_id,))
    m = cur.fetchone()
    if not m:
        conn.close()
        abort(404)

    role = session.get('role')
    allowed = False
    if role == 'admin':
        allowed = True
    elif role == 'faculty':
        allowed = _faculty_teaches_course(cur, session.get('faculty_id'), m['course_id'])
    elif role == 'student':
        cur.execute("""
            SELECT 1 FROM enrollments e
            JOIN students s ON e.student_id = s.student_id
            WHERE s.user_id = %s AND e.course_id = %s LIMIT 1
        """, (session['user_id'], m['course_id']))
        allowed = cur.fetchone() is not None
    conn.close()

    if not allowed:
        abort(403)

    return send_from_directory(
        _upload_dir(),
        m['file_path'],
        as_attachment=True,
        download_name=m['file_name'],
        mimetype=m['mime_type'],
    )


# =============================================================
# BULK GRADE ENTRY (A5) — one editable table per section
# =============================================================
@app.route('/faculty_bulk_grades/<int:section_id>', methods=['GET', 'POST'])
def faculty_bulk_grades(section_id):
    """Single-table grade entry for an entire section.

    Rows = enrolled students; columns = the standard component names
    plus ``final`` (letter grade). All edits in one POST.
    """
    if session.get('role') != 'faculty':
        return redirect(url_for('faculty_login'))

    faculty_id = session.get('faculty_id')
    conn = get_connection()
    cur = conn.cursor(dictionary=True)

    if not _faculty_owns_section(cur, faculty_id, section_id):
        conn.close()
        flash("That section is not allotted to you.", "danger")
        return redirect(url_for('faculty_courses'))

    components = ['Attendance', 'Assignment', 'Internal', 'External']
    valid_grades = {'O', 'A+', 'A', 'B+', 'B', 'C', 'P', 'F', 'AB', ''}

    cur.execute("""
        SELECT cs.section_label, cs.semester, c.course_name
        FROM course_sections cs JOIN courses c ON c.course_id = cs.course_id
        WHERE cs.section_id = %s
    """, (section_id,))
    section = cur.fetchone()

    if request.method == 'POST':
        cur.execute("""
            SELECT e.enrollment_id, e.student_id
            FROM enrollments e WHERE e.section_id = %s
        """, (section_id,))
        rows = cur.fetchall()
        updated = 0
        for row in rows:
            eid = row['enrollment_id']
            for comp in components:
                key = f"comp_{eid}_{comp}"
                raw = (request.form.get(key) or '').strip()
                if raw == '':
                    continue
                try:
                    marks = int(raw)
                except ValueError:
                    continue
                if not 0 <= marks <= 100:
                    continue
                cur.execute("""
                    INSERT INTO grade_components (enrollment_id, component_name, marks)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE marks=VALUES(marks)
                """, (eid, comp, marks))
                updated += 1
            grade = (request.form.get(f"grade_{eid}") or '').strip().upper()
            if grade in valid_grades and grade:
                cur.execute("UPDATE enrollments SET grade=%s WHERE enrollment_id=%s",
                            (grade, eid))
                updated += 1

                # Notify the student.
                cur2 = conn.cursor(dictionary=True)
                cur2.execute("""
                    SELECT u.user_id, c.course_name FROM enrollments e
                    JOIN students s ON e.student_id = s.student_id
                    JOIN users u ON s.user_id = u.user_id
                    JOIN courses c ON e.course_id = c.course_id
                    WHERE e.enrollment_id = %s
                """, (eid,))
                stu = cur2.fetchone()
                cur2.close()
                if stu:
                    _notify(cur, stu['user_id'], 'grade_posted',
                            f"Your grade for {stu['course_name']} is {grade}.",
                            url_for('student_courses'))
        _audit(cur, session['user_id'],
               f"Bulk-saved grades for section_id={section_id} ({updated} edits)")
        conn.commit()
        flash(f"Saved {updated} grade edits.", "success")
        return redirect(url_for('faculty_bulk_grades', section_id=section_id))

    # GET — assemble student × component matrix.
    cur.execute("""
        SELECT e.enrollment_id, s.roll_no, u.name AS student_name, e.grade
        FROM enrollments e
        JOIN students s ON e.student_id = s.student_id
        JOIN users u ON s.user_id = u.user_id
        WHERE e.section_id = %s
        ORDER BY s.roll_no
    """, (section_id,))
    students = cur.fetchall()

    # Pull existing component marks into a dict keyed by (enrollment_id, comp).
    cur.execute("""
        SELECT gc.enrollment_id, gc.component_name, gc.marks
        FROM grade_components gc
        JOIN enrollments e ON gc.enrollment_id = e.enrollment_id
        WHERE e.section_id = %s
    """, (section_id,))
    existing = {(r['enrollment_id'], r['component_name']): r['marks'] for r in cur.fetchall()}

    conn.close()
    return render_template(
        'faculty/bulk_grades.html',
        section=section, section_id=section_id,
        students=students, components=components, existing=existing,
        valid_grades=sorted(g for g in valid_grades if g),
    )
