"""WTForms for input validation across the app.

Forms here are *only* for validation — the global Flask-WTF CSRFProtect
already injects ``{{ csrf_token() }}`` into templates, so we subclass
the bare ``wtforms.Form`` (not ``FlaskForm``) and call ``form.validate()``
directly. This avoids double CSRF handling.

Field names mirror the existing template input ``name="..."`` attributes
so HTML changes aren't required when wiring a route to a form.
"""

from __future__ import annotations

import re

from wtforms import (
    Form,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import (
    AnyOf,
    DataRequired,
    Email,
    Length,
    NumberRange,
    Optional,
    Regexp,
    ValidationError,
)


# =============================================================
# Auth
# =============================================================
class LoginForm(Form):
    email = StringField("email", validators=[
        DataRequired(message="Email is required."),
        Email(message="Enter a valid email address."),
        Length(max=100),
    ])
    password = PasswordField("password", validators=[
        DataRequired(message="Password is required."),
        Length(min=1, max=128),
    ])


class OTPForm(Form):
    otp = StringField("otp", validators=[
        DataRequired(),
        Regexp(r"^\d{6}$", message="OTP must be exactly 6 digits."),
    ])


class ForgotPasswordForm(Form):
    email = StringField("email", validators=[
        DataRequired(),
        Email(),
        Length(max=100),
    ])


# Top-100 worst passwords condensed for an in-process check. Not a
# substitute for a real breach-list (HIBP) but rejects the obvious
# offenders. Kept short so it ships in-memory.
_COMMON_PASSWORDS = frozenset(
    p.lower() for p in (
        "password", "12345678", "123456789", "1234567890", "qwerty",
        "qwertyuiop", "111111", "1234567", "iloveyou", "admin", "welcome",
        "monkey", "letmein", "abc123", "starwars", "dragon", "passw0rd",
        "master", "football", "shadow", "superman", "michael", "jennifer",
        "trustno1", "1qaz2wsx", "qazwsx", "qwerty123", "password1",
        "password123", "admin123", "root", "toor", "sunshine", "princess",
    )
)


class _PasswordPolicyMixin:
    """Reusable password validators: length, common-password, optional
    no-overlap-with-email-or-name. Subclasses must provide a ``password``
    PasswordField. ``email`` is checked when the form has it; same for
    ``name`` if present.
    """

    def _check_password_policy(self, password: str) -> list[str]:
        errors: list[str] = []
        if not password:
            return errors
        if len(password) < 8:
            errors.append("Password must be at least 8 characters.")
        if password.lower() in _COMMON_PASSWORDS:
            errors.append(
                "This password is on the list of most-common breached "
                "passwords. Choose something less guessable."
            )
        # Reject pure digits / pure letters of any length.
        if password.isdigit() or password.isalpha():
            errors.append(
                "Password must contain a mix of letters and at least one "
                "non-letter character."
            )
        # Don't let the password match (or trivially extend) the email or name.
        for field_name in ("email", "name"):
            field = getattr(self, field_name, None)
            if field is None or not field.data:
                continue
            local = re.split(r"[@\s]", str(field.data))[0].lower()
            if local and local in password.lower():
                errors.append(
                    f"Password must not contain your {field_name}."
                )
                break
        return errors


class ResetPasswordForm(Form, _PasswordPolicyMixin):
    password = PasswordField("password", validators=[
        DataRequired(),
        Length(min=8, max=128, message="Password must be at least 8 characters."),
    ])
    # Field name matches the existing template input ``name="confirm"``.
    confirm = PasswordField("confirm", validators=[
        DataRequired(),
        Length(min=8, max=128),
    ])

    def validate(self, *args, **kwargs):
        if not super().validate(*args, **kwargs):
            return False
        ok = True
        if self.password.data != self.confirm.data:
            self.confirm.errors.append("Passwords do not match.")
            ok = False
        for err in self._check_password_policy(self.password.data or ""):
            self.password.errors.append(err)
            ok = False
        return ok


# =============================================================
# Student
# =============================================================
_SWD_CATEGORIES = ["Leave", "Hostel", "Medical", "Financial Aid"]


class NewSWDRequestForm(Form):
    category = SelectField(
        "category",
        choices=[(c, c) for c in _SWD_CATEGORIES],
        validators=[DataRequired(), AnyOf(_SWD_CATEGORIES)],
    )
    description = TextAreaField(
        "description",
        validators=[DataRequired(), Length(min=5, max=2000)],
    )


# =============================================================
# Faculty
# =============================================================
_VALID_GRADES = ["O", "A+", "A", "B+", "B", "C", "P", "F", "AB"]


class CourseForm(Form):
    course_name = StringField("course_name", validators=[
        DataRequired(), Length(min=2, max=100),
    ])
    credits = IntegerField("credits", validators=[
        DataRequired(), NumberRange(min=1, max=20),
    ])


class EnrollForm(Form):
    student_id = IntegerField("student_id", validators=[DataRequired(), NumberRange(min=1)])
    course_id = IntegerField("course_id", validators=[DataRequired(), NumberRange(min=1)])
    semester = IntegerField("semester", validators=[
        DataRequired(), NumberRange(min=1, max=8),
    ])


class GradeComponentForm(Form):
    component = StringField("component", validators=[
        DataRequired(), Length(min=1, max=50),
    ])
    marks = IntegerField("marks", validators=[
        DataRequired(), NumberRange(min=0, max=100),
    ])


class GradeForm(Form):
    enrollment_id = IntegerField("enrollment_id", validators=[
        DataRequired(), NumberRange(min=1),
    ])
    grade = SelectField(
        "grade",
        choices=[(g, g) for g in _VALID_GRADES],
        validators=[DataRequired(), AnyOf(_VALID_GRADES)],
    )


# =============================================================
# Admin
# =============================================================
_ROLES = ["student", "faculty", "admin"]


class CreateUserForm(Form):
    """Admin user creation. Role-specific fields are conditionally required
    based on ``role`` — checked in ``validate()``.
    """
    name = StringField("name", validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField("email", validators=[DataRequired(), Email(), Length(max=100)])
    role = SelectField(
        "role",
        choices=[(r, r.title()) for r in _ROLES],
        validators=[DataRequired(), AnyOf(_ROLES)],
    )

    # Student-only fields (Optional at the form level — required in validate()).
    roll_no = StringField("roll_no", validators=[Optional(), Length(max=20)])
    year_of_study = IntegerField("year_of_study", validators=[
        Optional(), NumberRange(min=1, max=4),
    ])
    current_semester = IntegerField("current_semester", validators=[
        Optional(), NumberRange(min=1, max=8),
    ])

    # Used by both student and faculty.
    dept_id = IntegerField("dept_id", validators=[Optional(), NumberRange(min=1)])

    def validate(self, *args, **kwargs):
        if not super().validate(*args, **kwargs):
            return False
        ok = True
        if self.role.data == "student":
            for field in (self.roll_no, self.year_of_study,
                          self.current_semester, self.dept_id):
                if field.data in (None, ""):
                    field.errors.append(
                        f"{field.name} is required for student accounts."
                    )
                    ok = False
        elif self.role.data == "faculty":
            if self.dept_id.data in (None, ""):
                self.dept_id.errors.append(
                    "dept_id is required for faculty accounts."
                )
                ok = False
        return ok


class EditStudentForm(Form):
    name = StringField("name", validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField("email", validators=[DataRequired(), Email(), Length(max=100)])
    roll_no = StringField("roll_no", validators=[DataRequired(), Length(max=20)])
    year_of_study = IntegerField("year_of_study", validators=[
        DataRequired(), NumberRange(min=1, max=4),
    ])
    current_semester = IntegerField("current_semester", validators=[
        DataRequired(), NumberRange(min=1, max=8),
    ])
    dept_id = IntegerField("dept_id", validators=[DataRequired(), NumberRange(min=1)])


class EditFacultyForm(Form):
    name = StringField("name", validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField("email", validators=[DataRequired(), Email(), Length(max=100)])
    dept_id = IntegerField("dept_id", validators=[DataRequired(), NumberRange(min=1)])


class DepartmentForm(Form):
    dept_name = StringField("dept_name", validators=[
        DataRequired(), Length(min=2, max=100),
    ])


class UpdateSemesterForm(Form):
    semester = IntegerField("semester", validators=[
        DataRequired(), NumberRange(min=1, max=8),
    ])


class BulkPromoteForm(Form):
    from_semester = IntegerField("from_semester", validators=[
        DataRequired(), NumberRange(min=1, max=8),
    ])
    to_semester = IntegerField("to_semester", validators=[
        DataRequired(), NumberRange(min=1, max=8),
    ])

    def validate(self, *args, **kwargs):
        if not super().validate(*args, **kwargs):
            return False
        if self.to_semester.data == self.from_semester.data:
            self.to_semester.errors.append(
                "Target semester must differ from source semester."
            )
            return False
        return True


class ResolveRequestForm(Form):
    action = SelectField(
        "action",
        choices=[("approved", "Approve"), ("rejected", "Reject"), ("pending", "Reset to Pending")],
        validators=[DataRequired(), AnyOf(["approved", "rejected", "pending"])],
    )


class ForwardRequestForm(Form):
    faculty_id = IntegerField("faculty_id", validators=[
        DataRequired(), NumberRange(min=1),
    ])
