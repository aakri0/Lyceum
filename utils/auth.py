from flask import session, redirect, url_for

def login_required():
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('home'))
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator
