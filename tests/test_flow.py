"""Uji otomatis alur lengkap SkillBridge (mengulang urutan Insomnia & Latihan Mandiri 1-6)."""
import hashlib
import hmac
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login(email: str, password: str) -> str:
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def send_callback(payload: dict):
    raw_body = json.dumps(payload).encode()
    signature = hmac.new(
        settings.payment_callback_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/payments/callback",
        data=raw_body,
        headers={"Content-Type": "application/json", "X-Signature": signature},
    )


@pytest.fixture(scope="module")
def student():
    email = f"siswa-{uuid.uuid4().hex[:8]}@mail.com"
    r = client.post(
        "/auth/register",
        json={"full_name": "Siswa Uji", "email": email, "password": "Rahasia123"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["data"]["role"] == "student"
    return {"email": email, "token": login(email, "Rahasia123")}


@pytest.fixture(scope="module")
def course():
    r = client.get("/courses")
    assert r.status_code == 200
    courses = r.json()["data"]
    for c in courses:
        detail = client.get(f"/courses/{c['id']}").json()["data"]
        if len(detail.get("modules", [])) == 4:
            return detail
    pytest.fail("Tidak ditemukan kursus dengan 4 modul")


def test_register_ignores_role_and_rejects_duplicates(student):
    r = client.post(
        "/auth/register",
        json={"full_name": "X Y", "email": student["email"], "password": "Rahasia123"},
    )
    assert r.status_code == 409
    r = client.post(
        "/auth/register",
        json={
            "full_name": "Hacker",
            "email": f"h-{uuid.uuid4().hex[:6]}@mail.com",
            "password": "Rahasia123",
            "role": "admin",
        },
    )
    assert r.status_code == 201
    assert r.json()["data"]["role"] == "student"


def test_validation_errors_use_standard_format():
    r = client.post(
        "/auth/register",
        json={"full_name": "A", "email": "bukan-email", "password": "123"},
    )
    body = r.json()
    assert r.status_code == 422
    assert set(body) == {"message", "data", "errors"} and body["errors"]


def test_auth_errors(student):
    assert client.get("/enrollments/mycourses").status_code == 401
    assert (
        client.get("/enrollments/mycourses", headers=auth("ngawur")).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": student["email"], "password": "salah-salah"},
        ).status_code
        == 401
    )


def test_roles(student, course):
    admin = login("admin@skillbridge.id", "Admin123!")
    r = client.post(
        "/enrollments", json={"course_id": course["id"]}, headers=auth(admin)
    )
    assert r.status_code == 403
    r = client.post(
        "/courses",
        json={
            "category_id": course["category_id"],
            "title": "Kursus Baru",
            "price": "1000.00",
        },
        headers=auth(student["token"]),
    )
    assert r.status_code == 403
    inst = login("instructor@skillbridge.id", "Instruktur123!")
    r = client.post(
        "/courses",
        json={
            "category_id": course["category_id"],
            "title": "Kursus Baru",
            "price": "1000.00",
        },
        headers=auth(inst),
    )
    assert r.status_code == 201


def test_course_lookup_errors():
    assert client.get(f"/courses/{uuid.uuid4()}").status_code == 404
    assert client.get("/courses/abc").status_code == 422


def test_full_purchase_flow(student, course):
    h = auth(student["token"])

    # enrollment -> order + invoice
    r = client.post("/enrollments", json={"course_id": course["id"]}, headers=h)
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    enrollment_id, invoice_id = d["enrollment"]["id"], d["invoice"]["id"]
    assert d["enrollment"]["status"] == "pending_payment"
    assert d["invoice"]["status"] == "unpaid" and d["order"]["status"] == "pending"

    # dua kali -> 409
    assert (
        client.post("/enrollments", json={"course_id": course["id"]}, headers=h).status_code
        == 409
    )

    module_id = course["modules"][0]["id"]
    progress = {"module_id": module_id, "status": "completed"}

    # belum bayar -> progress ditolak
    r = client.patch(
        f"/enrollments/{enrollment_id}/progress", json=progress, headers=h
    )
    assert r.status_code == 403

    # payment
    r = client.post(
        "/payments",
        json={"invoice_id": invoice_id, "method": "bank_transfer"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    pay = r.json()["data"]
    assert (
        client.post(
            "/payments",
            json={"invoice_id": invoice_id, "method": "qris"},
            headers=h,
        ).status_code
        == 409
    )

    # callback: token / signature salah
    cb = {
        "external_ref": pay["external_ref"],
        "status": "paid",
        "amount": pay["amount"],
    }
    assert client.post("/payments/callback", json=cb).status_code == 401
    assert (
        client.post(
            "/payments/callback", json=cb, headers={"X-Signature": "salah"}
        ).status_code
        == 401
    )

    # callback paid dengan HMAC valid
    r = send_callback(cb)
    assert r.status_code == 200 and r.json()["data"]["status"] == "paid"

    # idempotent
    r = send_callback(cb)
    assert r.status_code == 200 and "sudah pernah" in r.json()["message"]

    my = client.get("/enrollments/mycourses", headers=h).json()["data"]
    assert my[0]["status"] == "active" and my[0]["total_modules"] == 4

    # progress 25% -> 100%
    r = client.patch(
        f"/enrollments/{enrollment_id}/progress", json=progress, headers=h
    )
    assert r.status_code == 200
    assert r.json()["data"]["progress_percentage"] == 25.0
    for m in course["modules"][1:]:
        r = client.patch(
            f"/enrollments/{enrollment_id}/progress",
            json={"module_id": m["id"], "status": "completed"},
            headers=h,
        )
    assert r.json()["data"]["enrollment_status"] == "completed"
    assert r.json()["data"]["progress_percentage"] == 100.0


def test_failed_payment_allows_retry(student):
    h = auth(student["token"])
    inst = login("instructor@skillbridge.id", "Instruktur123!")
    cat = client.get("/courses").json()["data"][0]["category_id"]
    new = client.post(
        "/courses",
        json={
            "category_id": cat,
            "title": f"Retry {uuid.uuid4().hex[:5]}",
            "price": "50000.00",
        },
        headers=auth(inst),
    ).json()["data"]
    d = client.post("/enrollments", json={"course_id": new["id"]}, headers=h).json()[
        "data"
    ]
    inv = d["invoice"]["id"]
    p1 = client.post(
        "/payments", json={"invoice_id": inv, "method": "ewallet"}, headers=h
    ).json()["data"]

    r = send_callback(
        {"external_ref": p1["external_ref"], "status": "failed", "amount": p1["amount"]}
    )
    assert r.status_code == 200 and r.json()["data"]["status"] == "failed"
    r = client.post(
        "/payments", json={"invoice_id": inv, "method": "ewallet"}, headers=h
    )
    assert r.status_code == 201


# =====================================================================
# PENGUJIHAN TAMBAHAN: LATIHAN MANDIRI NO. 1 - 5
# =====================================================================


def test_exercise_1_get_course_modules(course):
    r = client.get(f"/courses/{course['id']}/modules")
    assert r.status_code == 200
    res = r.json()
    assert res["message"] == "Berhasil"
    assert len(res["data"]) == 4
    positions = [m["position"] for m in res["data"]]
    assert positions == sorted(positions)


def test_exercise_2_get_payment_detail_ownership(student, course):
    h = auth(student["token"])
    cat_id = course["category_id"]
    inst = login("instructor@skillbridge.id", "Instruktur123!")
    new_course = client.post(
        "/courses",
        json={
            "category_id": cat_id,
            "title": f"Test Pay {uuid.uuid4().hex[:4]}",
            "price": "150000.00",
        },
        headers=auth(inst),
    ).json()["data"]

    d = client.post(
        "/enrollments", json={"course_id": new_course["id"]}, headers=h
    ).json()["data"]
    pay = client.post(
        "/payments", json={"invoice_id": d["invoice"]["id"], "method": "qris"}, headers=h
    ).json()["data"]

    r = client.get(f"/payments/{pay['id']}", headers=h)
    assert r.status_code == 200
    assert r.json()["data"]["id"] == pay["id"]

    other_email = f"otherpay-{uuid.uuid4().hex[:6]}@mail.com"
    client.post(
        "/auth/register",
        json={
            "full_name": "Other User",
            "email": other_email,
            "password": "Rahasia123",
        },
    )
    other_token = login(other_email, "Rahasia123")
    assert (
        client.get(f"/payments/{pay['id']}", headers=auth(other_token)).status_code
        == 404
    )


def test_exercise_3_patch_course_permissions(student, course):
    inst = login("instructor@skillbridge.id", "Instruktur123!")
    admin = login("admin@skillbridge.id", "Admin123!")

    r = client.patch(
        f"/courses/{course['id']}",
        json={"title": "Hacked"},
        headers=auth(student["token"]),
    )
    assert r.status_code == 403

    r = client.patch(
        f"/courses/{course['id']}",
        json={"title": "Updated by Instructor"},
        headers=auth(inst),
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Updated by Instructor"

    r = client.patch(
        f"/courses/{course['id']}",
        json={"title": "Updated by Admin"},
        headers=auth(admin),
    )
    assert r.status_code == 200
    assert r.json()["data"]["title"] == "Updated by Admin"


def test_exercise_4_delete_course_with_active_enrollment(student, course):
    inst = login("instructor@skillbridge.id", "Instruktur123!")
    
    # 1. Buat kursus baru khusus pengujian delete
    cat_id = course["category_id"]
    new_course = client.post(
        "/courses",
        json={
            "category_id": cat_id,
            "title": f"Course Delete Test {uuid.uuid4().hex[:4]}",
            "price": "200000.00",
        },
        headers=auth(inst),
    ).json()["data"]

    # 2. Student mendaftar dan membayar kursus baru tersebut
    h = auth(student["token"])
    d = client.post("/enrollments", json={"course_id": new_course["id"]}, headers=h).json()["data"]
    pay = client.post(
        "/payments",
        json={"invoice_id": d["invoice"]["id"], "method": "bank_transfer"},
        headers=h,
    ).json()["data"]

    send_callback(
        {"external_ref": pay["external_ref"], "status": "paid", "amount": pay["amount"]}
    )

    # 3. Hapus kursus yang sudah memiliki pendaftaran aktif -> ditolak 409
    r = client.delete(f"/courses/{new_course['id']}", headers=auth(inst))
    assert r.status_code == 409
    assert "pendaftaran aktif" in r.json()["message"]