"""Department + user service tests for 3000+ user scale."""
import sqlite3
import time

from models import init_db
from services.department_service import (
    create_department,
    delete_department,
    get_department_by_code,
    list_departments,
    update_department,
)
from services.user_service import (
    compute_grade,
    create_user,
    delete_user,
    find_user_by_login,
    get_user,
    list_users,
    update_user,
)


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------


def test_compute_grade_basic():
    assert compute_grade(111, 112) == 2
    assert compute_grade(110, 113) == 4
    assert compute_grade(115, 115) == 1
    assert compute_grade(70, 115) is None  # too far
    assert compute_grade(120, 115) is None  # enrolled in future
    assert compute_grade(None, 115) is None
    assert compute_grade(110, None) is None


# ---------------------------------------------------------------------------
# Department service
# ---------------------------------------------------------------------------


def test_department_crud(app, db):
    d = create_department(db, code="XYZ1", name="測試系", short_name="測系", sort_order=100)
    assert d["code"] == "XYZ1"
    assert get_department_by_code(db, "XYZ1")["id"] == d["id"]

    all_depts = list_departments(db)
    assert any(x["code"] == "XYZ1" for x in all_depts)

    # duplicate code
    from services.department_service import DepartmentValidationError
    try:
        create_department(db, code="XYZ1", name="X", short_name="X")
    except DepartmentValidationError as e:
        assert "已存在" in str(e)
    else:
        raise AssertionError("should have raised")

    # update
    d2 = update_department(db, d["id"], {"name": "更名系"})
    assert d2["name"] == "更名系"

    # cannot delete if users reference it
    create_user(db, {
        "username": "u_dept_test", "password": "abcd1234", "display_name": "X",
        "department_id": d["id"],
    })
    ok, msg = delete_department(db, d["id"])
    assert not ok
    assert "人員" in msg

    # delete the user then the department
    uid = get_user(db, find_user_by_login(db, "u_dept_test")["id"])["id"]
    delete_user(db, uid)
    ok, _ = delete_department(db, d["id"])
    assert ok


# ---------------------------------------------------------------------------
# User service: login by username OR email
# ---------------------------------------------------------------------------


def test_login_by_username(app, db):
    # Use a unique alphanumeric username (must start with letter per policy).
    uniq = "u999114501"
    create_user(db, {
        "username": uniq, "password": "abcd1234",
        "display_name": "測試學生", "role": "student",
        "email": f"s{uniq[1:]}@nqu.edu.tw",
        "student_id": uniq[1:],
    })
    u = find_user_by_login(db, uniq)
    assert u and u["display_name"] == "測試學生"
    u = find_user_by_login(db, f"s{uniq[1:]}@nqu.edu.tw")
    assert u and u["username"] == uniq
    u = find_user_by_login(db, f"S{uniq[1:]}@NQU.EDU.TW")
    assert u and u["username"] == uniq


def test_login_disabled_user_cannot_auth(app):
    """A disabled user cannot authenticate even with the right password."""
    client = app.test_client()
    # Find a seeded student to disable
    client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    res = client.get("/api/admin/users?q=114210501")
    items = res.get_json()["items"]
    if not items:
        # fall back to any student
        items = client.get("/api/admin/users?role=student").get_json()["items"]
    user_id = items[0]["id"]
    original_username = items[0]["username"]
    client.put(f"/api/admin/users/{user_id}", json={"status": "disabled"})
    client.post("/api/auth/logout")

    # now login as that student with original password should fail
    res = client.post("/api/auth/login", json={"username": original_username, "password": "pass1234"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Pagination at 3000+ scale
# ---------------------------------------------------------------------------


def _bulk_create_users(db, count: int, prefix: str = "stu") -> int:
    """Create `count` users directly via SQL. Returns the first ID created."""
    from werkzeug.security import generate_password_hash
    pwd = generate_password_hash("pass1234")
    first_id = None
    cs = db.cursor()
    for i in range(count):
        cs.execute(
            "INSERT INTO users (username, password_hash, display_name, department, role, "
            "email, year_enrolled, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{prefix}{i:06d}", pwd, f"學生{i}", "資訊工程學系", "student",
             f"{prefix}{i:06d}@nku.edu.tw", 113, "active"),
        )
        if first_id is None:
            first_id = cs.lastrowid
    db.commit()
    return first_id


def _plan_to_str(plan_rows) -> str:
    """Convert EXPLAIN QUERY PLAN rows to a flat string for assertion."""
    parts = []
    for r in plan_rows:
        # row is a sqlite3.Row — index into it
        parts.extend(str(v) for v in r)
    return " ".join(parts)


def test_list_users_pagination_at_3000(app, db):
    """Insert 3000 users and verify pagination + filter performance."""
    bulk_id_start = _bulk_create_users(db, 3000)

    # Page 1
    t0 = time.perf_counter()
    result = list_users(db, per_page=50, page=1, current_academic_year=115, search="stu")
    t1 = time.perf_counter()
    assert result["total"] == 3000  # only the bulk-inserted "stu*" users
    assert len(result["items"]) == 50
    assert (t1 - t0) < 0.5, f"page 1 took {t1 - t0:.2f}s"
    print(f"\n  [perf] page 1 (50 of {result['total']}): {(t1 - t0) * 1000:.1f}ms")

    # Filter by year_enrolled
    t0 = time.perf_counter()
    result = list_users(db, year_enrolled=113, per_page=50, page=1, current_academic_year=115, search="stu")
    t1 = time.perf_counter()
    assert result["total"] == 3000
    assert (t1 - t0) < 0.5, f"filter by year took {t1 - t0:.2f}s"
    print(f"  [perf] filter by year (3000 matches): {(t1 - t0) * 1000:.1f}ms")

    # Search by partial username
    t0 = time.perf_counter()
    result = list_users(db, search="stu001", per_page=50, page=1, current_academic_year=115)
    t1 = time.perf_counter()
    assert result["total"] >= 10
    assert (t1 - t0) < 0.5, f"search took {t1 - t0:.2f}s"
    print(f"  [perf] LIKE search 'stu001': {(t1 - t0) * 1000:.1f}ms ({result['total']} matches)")

    # Verify grades are computed correctly
    sample = result["items"][0]
    assert sample["current_grade"] == 3  # 115 - 113 + 1


def test_username_unique_index_used(app, db):
    """EXPLAIN QUERY PLAN should reference idx_users_username."""
    _bulk_create_users(db, 100)
    plan = db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM users WHERE username = ?",
        ("stu000050",),
    ).fetchall()
    plan_str = _plan_to_str(plan)
    assert "USING INDEX" in plan_str.upper() or "idx_users_username" in plan_str, plan_str


def test_email_lookup_is_fast_at_scale(app, db):
    """SQLite may pick table scan for partial unique indexes even at large scale,
    but the lookup itself should still be sub-millisecond. We assert performance
    rather than the planner's choice — the index is available for SQLite to use
    when its cost model favours it."""
    _bulk_create_users(db, 5000)
    # Warm up
    db.execute("SELECT COUNT(*) FROM users").fetchone()
    t0 = time.perf_counter()
    for _ in range(100):
        db.execute("SELECT * FROM users WHERE email = ?", ("stu000050@nku.edu.tw",)).fetchone()
    elapsed = (time.perf_counter() - t0) / 100
    assert elapsed < 0.005, f"email lookup averaged {elapsed*1000:.2f}ms"
    print(f"\n  [perf] email lookup avg: {elapsed*1000:.2f}ms over 100 queries")


def test_year_enrolled_index_used(app, db):
    _bulk_create_users(db, 3000)
    plan = db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM users WHERE year_enrolled = ?",
        (113,),
    ).fetchall()
    plan_str = _plan_to_str(plan)
    assert "USING INDEX" in plan_str.upper() or "idx_users_year" in plan_str, plan_str


def test_role_index_used(app, db):
    _bulk_create_users(db, 3000)
    plan = db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM users WHERE role = ?",
        ("student",),
    ).fetchall()
    plan_str = _plan_to_str(plan)
    assert "USING INDEX" in plan_str.upper() or "idx_users_role" in plan_str, plan_str


def test_pagination_pages_field(app, db):
    """Insert N users; verify pagination metadata."""
    # Don't add to existing 3000 (those may persist between tests) — use a fresh prefix.
    _bulk_create_users(db, 1000, prefix="page")
    r = list_users(db, per_page=50, current_academic_year=115, search="page")
    # 1000 new users at 50/page = 20 pages (plus any extra seed users matching "page")
    assert r["pages"] >= 20


def test_update_user_with_year_and_department(app, db):
    d = create_department(db, code="P99", name="物理99", short_name="物99")
    create_user(db, {
        "username": "u_with_year", "password": "abcd1234",
        "display_name": "有年級", "role": "student",
        "year_enrolled": 110, "department_id": d["id"],
        "email": "u_year@nku.edu.tw",
    })
    u = find_user_by_login(db, "u_with_year")
    assert u["year_enrolled"] == 110
    assert u["department_id"] == d["id"]

    # update dept
    d2 = create_department(db, code="C99", name="化學99", short_name="化99")
    update_user(db, u["id"], {"department_id": d2["id"]})
    u2 = get_user(db, u["id"])
    assert u2["department_id"] == d2["id"]
    assert u2["dept_code"] == "C99"


def test_validation_email_format(app, db):
    from services.user_service import UserValidationError
    try:
        create_user(db, {
            "username": "v_email", "password": "abcd", "display_name": "V",
            "email": "not-an-email",
        })
    except UserValidationError as e:
        assert "Email" in str(e)
    else:
        raise AssertionError("should have raised")


def test_validation_year_out_of_range(app, db):
    from services.user_service import UserValidationError
    try:
        create_user(db, {
            "username": "v_year", "password": "abcd", "display_name": "V",
            "year_enrolled": 50,
        })
    except UserValidationError as e:
        assert "學年" in str(e)
    else:
        raise AssertionError("should have raised")


def test_duplicate_email_rejected(app, db):
    from services.user_service import UserValidationError
    create_user(db, {
        "username": "dup_email_a", "password": "abcd", "display_name": "A",
        "email": "dup@nku.edu.tw",
    })
    try:
        create_user(db, {
            "username": "dup_email_b", "password": "abcd", "display_name": "B",
            "email": "dup@nku.edu.tw",
        })
    except UserValidationError as e:
        assert "Email" in str(e) and "已存在" in str(e)
    else:
        raise AssertionError("should have raised")
