"""WTForms used for input validation on auth endpoints.

Forms here are *only* for validation — the global Flask-WTF CSRFProtect
already injects the CSRF token via ``{{ csrf_token() }}`` in templates,
so we use bare ``Form`` (not ``FlaskForm``) and call ``form.validate()``
directly. This avoids double CSRF handling.
"""

from wtforms import Form, PasswordField, StringField
from wtforms.validators import DataRequired, Email, Length, Regexp


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


class ResetPasswordForm(Form):
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
        if self.password.data != self.confirm.data:
            self.confirm.errors.append("Passwords do not match.")
            return False
        return True
