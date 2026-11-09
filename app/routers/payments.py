import hmac
import hashlib
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import authorize_role
from app.models import Enrollment, Invoice, Order, Payment, User
from app.schemas import (
    ApiResponse,
    PaymentCallbackIn,
    PaymentCreateIn,
    PaymentOut,
    ok,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("", status_code=201, response_model=ApiResponse[PaymentOut])
def create_payment(
    body: PaymentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("student")),
):
    invoice = db.get(Invoice, body.invoice_id)
    order = db.get(Order, invoice.order_id) if invoice else None
    if invoice is None or order.student_id != user.id:
        raise HTTPException(404, "Invoice tidak ditemukan")
    if invoice.status != "unpaid":
        raise HTTPException(409, "Invoice sudah dibayar atau tidak aktif")

    pending = db.scalar(
        select(Payment).where(
            Payment.invoice_id == invoice.id, Payment.status == "pending"
        )
    )
    if pending:
        raise HTTPException(
            409, "Masih ada pembayaran yang menunggu untuk invoice ini"
        )

    payment = Payment(
        invoice_id=invoice.id,
        method=body.method,
        amount=invoice.amount,
        external_ref=f"SB-{uuid.uuid4().hex[:12].upper()}",
    )
    db.add(payment)
    db.commit()
    return ok(payment, "Pembayaran dibuat, menunggu konfirmasi gateway")


@router.post("/callback", response_model=ApiResponse[PaymentOut])
async def payment_callback(
    request: Request,
    body: PaymentCallbackIn,
    x_signature: str | None = Header(default=None, alias="X-Signature"),
    db: Session = Depends(get_db),
):
    # ==========================================
    # SOAL NO. 5: Validasi Signature HMAC-SHA256 atas raw body
    # ==========================================
    raw_body = await request.body()
    expected_signature = hmac.new(
        settings.payment_callback_secret.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()

    if not x_signature or not hmac.compare_digest(x_signature, expected_signature):
        raise HTTPException(401, "Signature callback tidak valid")

    # 1) Kunci baris payment agar callback ganda tidak balapan
    payment = db.scalar(
        select(Payment)
        .where(Payment.external_ref == body.external_ref)
        .with_for_update()
    )
    if payment is None:
        raise HTTPException(404, "Pembayaran tidak ditemukan")

    # 2) Idempotent: Callback yang sudah diproses tidak diproses ulang
    if payment.status != "pending":
        return ok(payment, "Callback sudah pernah diproses")

    # 3) Nominal harus cocok
    if body.amount != payment.amount:
        raise HTTPException(
            422, "Nominal callback tidak sesuai dengan tagihan"
        )

    # ==========================================
    # SOAL NO. 4: Cek status kedaluwarsa invoice (expired_at)
    # ==========================================
    invoice = db.get(Invoice, payment.invoice_id)
    now = datetime.now(timezone.utc)

    if invoice and invoice.expired_at and invoice.expired_at < now:
        invoice.status = "expired"
        payment.status = "failed"
        db.commit()
        raise HTTPException(409, "Invoice sudah kedaluwarsa")

    if body.status == "failed":
        payment.status = "failed"
        db.commit()
        return ok(payment, "Pembayaran ditandai gagal")

    # 4) PAID: Update payment, invoice, order, enrollment secara konsisten
    payment.status = "paid"
    payment.paid_at = now

    invoice.status = "paid"
    invoice.paid_at = now

    order = db.get(Order, invoice.order_id)
    order.status = "paid"

    enrollment = db.scalar(select(Enrollment).where(Enrollment.order_id == order.id))
    enrollment.status = "active"

    db.commit()
    return ok(payment, "Pembayaran berhasil, enrollment aktif")


# ==========================================
# LATIHAN MANDIRI NO. 2: GET /payments/{id}
# ==========================================
@router.get("/{id}", response_model=ApiResponse[PaymentOut])
def get_payment_detail(
    id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("student", "instructor", "admin")),
):
    payment = db.get(Payment, id)
    if payment is None:
        raise HTTPException(404, "Pembayaran tidak ditemukan")

    invoice = db.get(Invoice, payment.invoice_id)
    if invoice is None:
        raise HTTPException(404, "Pembayaran tidak ditemukan")

    order = db.get(Order, invoice.order_id)
    if order is None or (user.role == "student" and order.student_id != user.id):
        raise HTTPException(404, "Pembayaran tidak ditemukan")

    return ok(payment)