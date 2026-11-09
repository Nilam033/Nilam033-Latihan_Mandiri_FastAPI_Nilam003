import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.deps import authorize_role
from app.models import Category, Course, CourseModule, Enrollment, User
from app.schemas import (
    ApiResponse,
    CourseCreateIn,
    CourseDetailOut,
    CourseOut,
    CourseUpdateIn,
    ModuleOut,
    ok,
)

router = APIRouter(prefix="/courses", tags=["Courses"])


@router.get("", response_model=ApiResponse[list[CourseOut]])
def list_courses(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    stmt = select(Course).where(Course.is_published.is_(True))
    if q:
        stmt = stmt.where(Course.title.ilike(f"%{q}%"))
    if category_id:
        stmt = stmt.where(Course.category_id == category_id)
    stmt = stmt.order_by(Course.created_at.desc()).limit(limit).offset(offset)
    return ok(db.scalars(stmt).all())


@router.get("/{course_id}", response_model=ApiResponse[CourseDetailOut])
def get_course(course_id: uuid.UUID, db: Session = Depends(get_db)):
    course = db.scalar(
        select(Course)
        .where(Course.id == course_id, Course.is_published.is_(True))
        .options(selectinload(Course.modules))
    )
    if course is None:
        raise HTTPException(404, "Kursus tidak ditemukan")
    return ok(course)


@router.post("", status_code=201, response_model=ApiResponse[CourseOut])
def create_course(
    body: CourseCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("instructor", "admin")),
):
    if db.get(Category, body.category_id) is None:
        raise HTTPException(404, "Kategori tidak ditemukan")
    course = Course(**body.model_dump(), instructor_id=user.id)
    db.add(course)
    db.commit()
    return ok(course, "Kursus berhasil dibuat")


# ==========================================
# LATIHAN MANDIRI NO. 1: GET /courses/{course_id}/modules
# ==========================================
@router.get("/{course_id}/modules", response_model=ApiResponse[list[ModuleOut]])
def get_course_modules(course_id: uuid.UUID, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if course is None or not course.is_published:
        raise HTTPException(404, "Kursus tidak ditemukan")

    modules = db.scalars(
        select(CourseModule)
        .where(CourseModule.course_id == course_id)
        .order_by(CourseModule.position.asc())
    ).all()

    return ok(modules)


# ==========================================
# LATIHAN MANDIRI NO. 3: PATCH /courses/{course_id}
# ==========================================
@router.patch("/{course_id}", response_model=ApiResponse[CourseOut])
def update_course(
    course_id: uuid.UUID,
    body: CourseUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("instructor", "admin")),
):
    # 1. Cek apakah kursus ada
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Kursus tidak ditemukan")

    # 2. Cek hak akses: Instructor hanya boleh edit kursusnya sendiri
    if user.role != "admin" and course.instructor_id != user.id:
        raise HTTPException(403, "Anda tidak memiliki akses untuk mengubah kursus ini")

    # 3. Update data yang dikirimkan saja
    update_data = body.model_dump(exclude_unset=True)
    if "category_id" in update_data and update_data["category_id"] is not None:
        if db.get(Category, update_data["category_id"]) is None:
            raise HTTPException(404, "Kategori tidak ditemukan")

    for key, value in update_data.items():
        setattr(course, key, value)

    db.commit()
    db.refresh(course)
    return ok(course, "Kursus berhasil diperbarui")

# ==========================================
# LATIHAN MANDIRI NO. 4: DELETE /courses/{course_id}
# ==========================================
@router.delete("/{course_id}", status_code=200, response_model=ApiResponse[None])
def delete_course(
    course_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(authorize_role("instructor", "admin")),
):
    # 1. Cek apakah kursus ada
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "Kursus tidak ditemukan")

    # 2. Cek Hak Akses: Instructor hanya boleh hapus kursusnya sendiri
    if user.role != "admin" and course.instructor_id != user.id:
        raise HTTPException(403, "Anda tidak memiliki akses untuk menghapus kursus ini")

    # 3. Cek apakah kursus sudah dibeli / punya enrollment
    has_enrollment = db.scalar(
        select(Enrollment).where(Enrollment.course_id == course_id)
    )
    if has_enrollment:
        raise HTTPException(
            409, "Kursus tidak dapat dihapus karena sudah memiliki pendaftaran aktif"
        )

    # 4. Hapus kursus dari database
    db.delete(course)
    db.commit()

    return ok(None, "Kursus berhasil dihapus")