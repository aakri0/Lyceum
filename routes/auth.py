"""Generic auth endpoints (OTP verify/resend, password reset flows).

Routes registered on the shared ``app`` object via ``@app.route``.
Endpoint names match function names so existing ``url_for`` calls in
templates continue to resolve unchanged.
"""

import random
import uuid

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
from forms import ForgotPasswordForm, OTPForm, ResetPasswordForm


@app.route('/verify_otp', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def verify_otp():
    if request.method == 'POST':
        form = OTPForm(request.form)
        if not form.validate():
            flash("OTP must be 6 digits.", "danger")
            return render_template('verify_otp.html')
        otp = form.otp.data
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
@limiter.limit("3 per minute; 10 per hour")
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
@limiter.limit("10 per minute; 30 per hour", methods=["POST"])
def force_reset_password():
    if 'user_id' not in session:
        return redirect(url_for('home'))

    if request.method == 'POST':
        form = ResetPasswordForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(err, "danger")
            return redirect(url_for('force_reset_password'))
        pwd = form.password.data

        hashed = bcrypt.generate_password_hash(pwd).decode()

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            UPDATE users
            SET password=%s, force_reset=0
            WHERE user_id=%s
        """, (hashed, session['user_id']))
        _audit(cur, session['user_id'], "Password changed via forced first-login reset")
        conn.commit()
        conn.close()

        flash("Password updated successfully", "success")
        return redirect(url_for('home'))

    return render_template('force_reset_password.html')
@app.route('/forgot_password', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot_password():
    if request.method == 'POST':
        form = ForgotPasswordForm(request.form)
        if not form.validate():
            # Don't reveal whether the input was malformed vs unknown — still
            # show the generic "if email exists" message to avoid enumeration.
            flash("If email exists, reset link has been sent", "info")
            return redirect(url_for('home'))
        email = form.email.data

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

            reset_link = url_for('reset_password', token=token, _external=True)
            send_password_reset_email(email, reset_link)

        conn.close()
        flash("If email exists, reset link has been sent", "info")
        return redirect(url_for('home'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
@limiter.limit("10 per minute; 30 per hour")
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
        form = ResetPasswordForm(request.form)
        if not form.validate():
            for field, errors in form.errors.items():
                for err in errors:
                    flash(err, "danger")
            conn.close()
            return redirect(request.url)
        pwd = form.password.data

        hashed = bcrypt.generate_password_hash(pwd).decode()
        cur.execute("""
            UPDATE users SET password=%s WHERE user_id=%s
        """, (hashed, record['user_id']))
        cur.execute("DELETE FROM password_resets WHERE user_id=%s", (record['user_id'],))
        _audit(cur, record['user_id'], "Password reset via emailed reset-link")
        conn.commit()
        conn.close()

        flash("Password reset successful", "success")
        return redirect(url_for('home'))

    conn.close()
    return render_template('reset_password.html')
