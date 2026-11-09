# Laporan Pengerjaan Latihan Mandiri - SkillBridge API

## 1. Rangkuman Implementasi Latihan Mandiri (Soal 1 - 6)

1. **Exercise 1 (`GET /courses/{id}/modules`):**
   * Mengembalikan daftar modul yang terurut berdasarkan kolom `position ASC`.
2. **Exercise 2 (`GET /payments/{id}`):**
   * Pengecekan hak akses kepemilikan pembayaran (student hanya bisa melihat pembayaran milik sendiri, menolak akses student lain dengan `404`).
3. **Exercise 3 (`PATCH /courses/{id}`):**
   * Validasi role update (instructor hanya boleh edit kursus miliknya, admin bebas edit semua, student ditolak `403`).
4. **Exercise 4 (`DELETE /courses/{id}` & Column `expired_at`):**
   * Validasi hapus kursus (jika sudah ada pendaftaran/enrollment aktif, sistem menolak dengan `409 Conflict`).
   * Menambahkan kolom `expired_at` pada model dan tabel `invoices`. Callback pembayaran untuk invoice kedaluwarsa ditolak dengan status `409 Conflict`.
5. **Exercise 5 (HMAC-SHA256 Signature Validation):**
   * Memperbarui validasi callback pembayaran dari token statis menjadi verifikasi signature **HMAC-SHA256** atas *raw body* request menggunakan header `X-Signature`.
6. **Exercise 6 (Unit Testing Pytest):**
   * Menulis unit test di `tests/test_flow.py` untuk memastikan seluruh alur utama dan latihan mandiri lulus pengujian otomatis.

---

## 2. Bukti Pengujian Otomatis (Pytest)

Seluruh 11 pengujian unit test pada file `tests/test_flow.py` telah dieksekusi dan dinyatakan **100% PASSED (LULUS)**:

```text
============================= test session starts =============================
collected 11 items

tests/test_flow.py::test_register_ignores_role_and_rejects_duplicates PASSED [  9%]
tests/test_flow.py::test_validation_errors_use_standard_format PASSED        [ 18%]
tests/test_flow.py::test_auth_errors PASSED                                    [ 27%]
tests/test_flow.py::test_roles PASSED                                          [ 36%]
tests/test_flow.py::test_course_lookup_errors PASSED                           [ 45%]
tests/test_flow.py::test_full_purchase_flow PASSED                             [ 54%]
tests/test_flow.py::test_failed_payment_allows_retry PASSED                    [ 63%]
tests/test_flow.py::test_exercise_1_get_course_modules PASSED                  [ 72%]
tests/test_flow.py::test_exercise_2_get_payment_detail_ownership PASSED        [ 81%]
tests/test_flow.py::test_exercise_3_patch_course_permissions PASSED            [ 90%]
tests/test_flow.py::test_exercise_4_delete_course_with_active_enrollment PASSED [100%]

======================== 11 passed, 5 warnings in 9.40s ========================