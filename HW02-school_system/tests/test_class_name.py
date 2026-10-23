"""Tests for the auto-computed class_name feature."""
from services.user_service import (
    compute_class_name,
    compute_grade,
    create_user,
    get_user,
    get_user_by_username,
    update_user,
)
from config import TestConfig


# ---------------------------------------------------------------------------
# Pure unit tests
# ---------------------------------------------------------------------------


def test_compute_class_name_basic():
    """資工 學年 114 -> 在 115 學年是大二 -> 資工二A"""
    assert compute_class_name("資工", 114, "A", 115) == "資工二A"


def test_compute_class_name_advances_each_year():
    """Same student -> different display per academic year without editing."""
    assert compute_class_name("資工", 114, "A", 115) == "資工二A"
    assert compute_class_name("資工", 114, "A", 116) == "資工三A"
    assert compute_class_name("資工", 114, "A", 117) == "資工四A"
    assert compute_class_name("資工", 114, "A", 118) == "資工五A"  # 延畢


def test_compute_class_name_different_dept():
    assert compute_class_name("企管", 115, "A", 115) == "企管一A"
    assert compute_class_name("電機", 113, "B", 115) == "電機三B"
    assert compute_class_name("資訊處", None, "A", 115) is None  # 行政單位不適用


def test_compute_class_name_no_section_returns_none():
    assert compute_class_name("資工", 114, None, 115) is None
    assert compute_class_name("資工", 114, "", 115) is None


def test_compute_class_name_no_year_returns_none():
    assert compute_class_name("資工", None, "A", 115) is None


def test_compute_class_name_out_of_range_returns_none():
    # 1 年級以下 / 8 年級以上
    assert compute_class_name("資工", 116, "A", 115) is None  # 還沒入學
    assert compute_class_name("資工", 100, "A", 115) is None  # 16 年級


def test_compute_class_name_supports_sub_sections():
    """A1 / B1 等副班別也支援"""
    assert compute_class_name("資工", 114, "A1", 115) == "資工二A1"


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------


def test_create_user_persists_section_and_computes_class_name(app, db):
    u = create_user(db, {
        "username": "cls_test_1", "password": "abcd1234",
        "display_name": "班級測試", "role": "student",
        "student_id": "115210999",
        "department_id": _get_dept_id(db, "CS"),
        "year_enrolled": 115,
        "section": "A",
    })
    assert u["section"] == "A"
    assert u["class_name"] == "資工一A"
    assert u["current_grade"] == 1


def test_class_name_auto_updates_on_year_change(app, db):
    """When admin updates year_enrolled, class_name auto-advances."""
    u = create_user(db, {
        "username": "cls_test_2", "password": "abcd1234",
        "display_name": "升級測試", "role": "student",
        "student_id": "115210998",
        "department_id": _get_dept_id(db, "CS"),
        "year_enrolled": 114,
        "section": "B",
    })
    assert u["class_name"] == "資工二B"

    # Simulate 116 academic year by overriding ACADEMIC_YEAR
    app.config["ACADEMIC_YEAR"] = 116
    # Update nothing — but re-fetch user; their year_enrolled is still 114
    # so computed grade should now be 3 in 116 學年.
    with app.app_context():
        refreshed = get_user(db, u["id"])
    assert refreshed["class_name"] == "資工三B"


def test_changing_section_updates_class_name(app, db):
    u = create_user(db, {
        "username": "cls_test_3", "password": "abcd1234",
        "display_name": "換班測試", "role": "student",
        "student_id": "115210997",
        "department_id": _get_dept_id(db, "CS"),
        "year_enrolled": 114,
        "section": "A",
    })
    assert u["class_name"] == "資工二A"

    update_user(db, u["id"], {"section": "B"})
    refreshed = get_user(db, u["id"])
    assert refreshed["class_name"] == "資工二B"


def test_class_name_for_teacher_is_none(app, db):
    """Teachers don't have a class_name regardless of fields."""
    u = create_user(db, {
        "username": "cls_test_t", "password": "abcd1234",
        "display_name": "老師測試", "role": "teacher",
    })
    assert u["class_name"] is None


def _get_dept_id(db, code):
    return db.execute("SELECT id FROM departments WHERE code = ?", (code,)).fetchone()["id"]
