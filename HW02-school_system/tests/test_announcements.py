"""Announcement API + service tests."""
from services.announcement_service import (
    get_announcement,
    list_announcements,
    upsert_announcement,
)


def test_seed_announcements_loaded(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/api/announcements")
    assert res.status_code == 200
    items = res.get_json()["announcements"]
    slugs = {a["slug"] for a in items}
    assert "course-selection" in slugs
    assert "paperless-transcript" in slugs


def test_get_announcement_by_slug(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/api/announcements/course-selection")
    assert res.status_code == 200
    body = res.get_json()["announcement"]
    assert "選課" in body["title"]
    assert body["content"]


def test_get_announcement_404(app):
    client = app.test_client()
    client.post("/api/auth/login", json={"username": "s114210501", "password": "pass1234"})
    res = client.get("/api/announcements/no-such-slug")
    assert res.status_code == 404


def test_upsert_creates_then_updates(app, db):
    with app.app_context():
        a = upsert_announcement(
            db,
            slug="temp",
            title="Temp",
            category="測試",
            content="hello",
            issued_at="2026-01-01",
            author="tester",
        )
        assert a["title"] == "Temp"
        b = upsert_announcement(
            db,
            slug="temp",
            title="Temp v2",
            category="測試",
            content="hello v2",
            issued_at="2026-01-02",
            author="tester",
        )
        assert b["title"] == "Temp v2"
        assert len(list_announcements(db)) >= 1
        assert get_announcement(db, "temp")["title"] == "Temp v2"