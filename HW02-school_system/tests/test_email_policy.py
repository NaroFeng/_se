"""Tests for the @nqu.edu.tw email policy."""
from services.user_service import create_user, derive_email, get_user_by_email


def test_derive_email_student_uses_student_id():
    assert derive_email("student", "114210501", "s114210501") == "s114210501@nqu.edu.tw"


def test_derive_email_teacher_falls_back_to_username():
    assert derive_email("teacher", None, "wsm") == "wsm@nqu.edu.tw"


def test_derive_email_admin_uses_username():
    assert derive_email("admin", None, "admin") == "admin@nqu.edu.tw"


def test_derive_email_explicit_overrides():
    assert derive_email("student", "114210501", "s114210501", explicit="test@x.com") == "test@x.com"


def test_derive_email_empty_inputs():
    assert derive_email("student", None, None) is None
    assert derive_email("teacher", "", "") is None


def test_create_user_student_sets_email_from_student_id(app, db):
    user = create_user(db, {
        "username": "stu_new", "password": "abcd1234",
        "display_name": "測試", "role": "student",
        "student_id": "115299999",
    })
    assert user["email"] == "s115299999@nqu.edu.tw"


def test_create_user_explicit_email_overrides_policy(app, db):
    user = create_user(db, {
        "username": "guest", "password": "abcd1234",
        "display_name": "Guest", "role": "student",
        "student_id": "115288888",
        "email": "custom@example.com",
    })
    assert user["email"] == "custom@example.com"


def test_create_user_teacher_email_uses_username(app, db):
    user = create_user(db, {
        "username": "new_teacher", "password": "abcd1234",
        "display_name": "New Teacher", "role": "teacher",
    })
    assert user["email"] == "new_teacher@nqu.edu.tw"


def test_seed_users_have_nqu_emails(app):
    """End-to-end: re-init and check seeded emails."""
    from models import init_db
    with app.app_context():
        init_db(app)
    db = app.config["DATABASE_PATH"]
    import sqlite3
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    feng = conn.execute("SELECT email, student_id, role FROM users WHERE username='s114210501'").fetchone()
    assert feng["email"] == f"s{feng['student_id']}@nqu.edu.tw"
    admin = conn.execute("SELECT email, role FROM users WHERE username='admin'").fetchone()
    assert admin["email"] == "admin@nqu.edu.tw"
    conn.close()
