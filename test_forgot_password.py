"""
Automated test suite verifying:
1. Forgot Password endpoint validations (/api/send-forgot-password-otp).
2. OTP generation and email dispatch for password recovery.
3. OTP verification & password reset logic (/api/reset-password).
4. Verification that old password is invalidated.
5. Verification that new password authenticates successfully.
6. Standalone /forgot-password page route.
"""
import sys
import os
import uuid

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
import firebase_db
from auth_jwt import verify_password


def run_forgot_password_tests():
    print("=" * 65)
    print("Running Automated Tests: Professional Forgot Password Workflow")
    print("=" * 65)

    client = app.test_client()

    # Create a dedicated test user in Firebase / local DB
    test_id = uuid.uuid4().hex[:6]
    test_name = f"Test Officer {test_id}"
    test_email = f"officer.{test_id}@example.com"
    test_mobile = f"987{uuid.uuid4().int % 10000000:07d}"
    initial_password = "InitialPassword@123"
    new_password = "BrandNewSecurePassword@456"

    user = firebase_db.create_user(
        contact=test_email,
        name=test_name,
        password=initial_password,
        mobile=test_mobile,
        email=test_email
    )
    print(f"\n[Setup] Created test user: {test_name} | Email: {test_email} | Mobile: {test_mobile}")

    # 1. Test /forgot-password route
    print("\n[Test 1] Testing standalone /forgot-password route...")
    res = client.get('/forgot-password')
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert b"Reset Your" in res.data
    print("[PASS] Standalone /forgot-password page rendered successfully.")

    # 2. Test OTP request with empty contact
    print("\n[Test 2] Testing /api/send-forgot-password-otp with empty contact...")
    res = client.post('/api/send-forgot-password-otp', json={"contact": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    print("[PASS] Successfully rejected empty contact request.")

    # 3. Test OTP request with non-existent contact
    print("\n[Test 3] Testing /api/send-forgot-password-otp with non-existent user...")
    res = client.post('/api/send-forgot-password-otp', json={"contact": "non_existent_user_999@test.com"})
    assert res.status_code == 404
    data = res.get_json()
    assert data["success"] is False
    print("[PASS] Successfully returned 404 for non-existent user.")

    # 4. Test OTP request with registered mobile number
    print("\n[Test 4] Testing /api/send-forgot-password-otp using Mobile Number...")
    res = client.post('/api/send-forgot-password-otp', json={"contact": test_mobile})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.get_json()
    assert data["success"] is True
    assert "email" in data or "masked_email" in data
    print(f"[PASS] Successfully recognized mobile number and routed OTP to email: {data.get('masked_email')}")

    # Inspect session for OTP
    with client.session_transaction() as sess:
        pending = sess.get('pending_password_reset')
        assert pending is not None, "Pending password reset missing from session"
        otp_code = pending["otp"]
        assert len(otp_code) == 6, f"Expected 6 digits, got {otp_code}"
        print(f"[PASS] 6-Digit OTP generated & stored securely in session: {otp_code}")

    # 5. Test reset with wrong OTP
    print("\n[Test 5] Testing /api/reset-password with invalid OTP...")
    res = client.post('/api/reset-password', json={
        "contact": test_email,
        "entered_otp": "000000",
        "new_password": new_password,
        "confirm_password": new_password
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    print("[PASS] Invalid OTP correctly rejected.")

    # 6. Test reset with mismatched passwords
    print("\n[Test 6] Testing /api/reset-password with mismatched passwords...")
    res = client.post('/api/reset-password', json={
        "contact": test_email,
        "entered_otp": otp_code,
        "new_password": new_password,
        "confirm_password": "CompletelyDifferentPassword"
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    print("[PASS] Password mismatch correctly rejected.")

    # 7. Test reset with too short password
    print("\n[Test 7] Testing /api/reset-password with password shorter than 6 characters...")
    res = client.post('/api/reset-password', json={
        "contact": test_email,
        "entered_otp": otp_code,
        "new_password": "123",
        "confirm_password": "123"
    })
    assert res.status_code == 400
    print("[PASS] Short password correctly rejected.")

    # 8. Test successful password reset
    print("\n[Test 8] Testing /api/reset-password with valid OTP and matching passwords...")
    res = client.post('/api/reset-password', json={
        "contact": test_email,
        "entered_otp": otp_code,
        "new_password": new_password,
        "confirm_password": new_password
    })
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.get_json()
    assert data["success"] is True
    print(f"[PASS] Password successfully updated: {data.get('message')}")

    # 9. Verify database record
    print("\n[Test 9] Verifying database record reflects updated password hash...")
    updated_user = firebase_db.get_user_by_contact(test_email)
    assert updated_user is not None
    assert verify_password(updated_user["password_hash"], new_password) is True
    assert verify_password(updated_user["password_hash"], initial_password) is False
    print("[PASS] Verified: Old password no longer validates; New password validates perfectly.")

    # 10. Test Login using old password (should fail)
    print("\n[Test 10] Testing Login attempt with OLD password...")
    res = client.post('/login', data={"contact": test_email, "password": initial_password})
    assert b"Invalid Credentials" in res.data
    print("[PASS] Old password was rejected on login.")

    # 11. Test Login using new password (should succeed)
    print("\n[Test 11] Testing Login attempt with NEW password...")
    res = client.post('/login', data={"contact": test_email, "password": new_password})
    assert res.status_code == 302, f"Expected 302 redirect to dashboard, got {res.status_code}"
    assert "/dashboard" in res.headers.get("Location", "")
    print("[PASS] New password authenticated successfully and redirected to /dashboard.")

    print("\n" + "=" * 65)
    print("ALL FORGOT PASSWORD TESTS PASSED PERFECTLY! (11/11)")
    print("=" * 65)


if __name__ == '__main__':
    run_forgot_password_tests()
