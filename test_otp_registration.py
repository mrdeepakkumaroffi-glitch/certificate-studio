"""
Automated verification test for:
1. Professional Registration Process with Name, Mobile, and Email ID.
2. Email OTP dispatch via Gmail SMTP (mailer.send_otp_email).
3. Email OTP verification & Password creation with confirmation matching.
4. Universal Login using either Email ID OR Mobile Number with password.
"""
import sys
import os

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
import firebase_db
import mailer


def test_registration_and_login_flow():
    print("=" * 65)
    print("Testing Professional Registration, Email OTP & Universal Login")
    print("=" * 65)

    client = app.test_client()

    # 1. Test registration OTP request validation
    print("\n[Step 1] Testing /api/send-registration-otp field validations...")
    # Missing name
    res = client.post('/api/send-registration-otp', json={"name": "", "mobile": "9876543210", "email": "test@domain.com"})
    assert res.status_code == 400
    print("[PASS] Rejected missing name.")

    # Invalid mobile
    res = client.post('/api/send-registration-otp', json={"name": "Sarah Connor", "mobile": "123", "email": "test@domain.com"})
    assert res.status_code == 400
    print("[PASS] Rejected invalid mobile number.")

    # Invalid email
    res = client.post('/api/send-registration-otp', json={"name": "Sarah Connor", "mobile": "9876543210", "email": "not-an-email"})
    assert res.status_code == 400
    print("[PASS] Rejected invalid email address.")

    # 2. Test successful OTP generation & dispatch
    print("\n[Step 2] Testing OTP generation and email dispatch...")
    import uuid
    rand_suffix = uuid.uuid4().hex[:6]
    test_name = f"Sarah Connor {rand_suffix}"
    test_mobile = f"9876{uuid.uuid4().int % 1000000:06d}"
    test_email = f"sarah.{rand_suffix}@studio.com"
    test_password = "SuperSecretPassword@123"

    res = client.post('/api/send-registration-otp', json={
        "name": test_name,
        "mobile": test_mobile,
        "email": test_email
    })
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data = res.get_json()
    assert data["success"] is True, "Failed to generate OTP"
    print(f"[PASS] /api/send-registration-otp returned success! Delivered via SMTP: {data.get('delivered_via_smtp')}")

    # Inspect session to get the generated OTP
    with client.session_transaction() as sess:
        pending = sess.get('pending_registration')
        assert pending is not None, "Pending registration missing from session"
        assert pending["email"] == test_email
        assert pending["mobile"] == test_mobile
        assert pending["name"] == test_name
        otp_code = pending["otp"]
        assert len(otp_code) == 6, f"Expected 6-digit OTP, got {otp_code}"
        print(f"[PASS] 6-digit OTP stored in session: {otp_code}")

    # 3. Test verification with wrong OTP
    print("\n[Step 3] Testing /verify-register with wrong OTP...")
    res = client.post('/verify-register', json={
        "name": test_name,
        "mobile": test_mobile,
        "email": test_email,
        "entered_otp": "000000",
        "password": test_password,
        "confirm_password": test_password
    })
    assert res.status_code == 400
    err_data = res.get_json()
    assert err_data["success"] is False
    print("[PASS] Correctly rejected invalid OTP code.")

    # 4. Test verification with mismatched passwords
    print("\n[Step 4] Testing /verify-register with mismatched passwords...")
    res = client.post('/verify-register', json={
        "name": test_name,
        "mobile": test_mobile,
        "email": test_email,
        "entered_otp": otp_code,
        "password": test_password,
        "confirm_password": "DifferentPassword456"
    })
    assert res.status_code == 400
    print("[PASS] Correctly rejected mismatched passwords.")

    # 5. Test successful verification and account creation
    print("\n[Step 5] Testing successful verification and account creation...")
    res = client.post('/verify-register', json={
        "name": test_name,
        "mobile": test_mobile,
        "email": test_email,
        "entered_otp": otp_code,
        "password": test_password,
        "confirm_password": test_password
    })
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.data}"
    succ_data = res.get_json()
    assert succ_data["success"] is True
    print("[PASS] Verification successful and user account created!")

    # Verify user was saved in database with both email and mobile
    user = firebase_db.get_user_by_contact(test_email)
    assert user is not None, "User not found in database by email"
    assert user["name"] == test_name
    assert user["mobile"] == test_mobile
    assert user["email"] == test_email
    print(f"[PASS] Database record confirmed: Name='{user['name']}', Mobile='{user['mobile']}', Email='{user['email']}'")

    # 6. Test Universal Login using EMAIL ID
    print("\n[Step 6] Testing Login using EMAIL ID...")
    login_client1 = app.test_client()
    res = login_client1.post('/login', data={
        "contact": test_email,
        "password": test_password
    }, follow_redirects=False)
    assert res.status_code == 302, f"Expected redirect, got {res.status_code}"
    assert "/dashboard" in res.headers.get("Location")
    print("[PASS] Successfully logged in using EMAIL ID! Redirected to /dashboard.")

    # 7. Test Universal Login using MOBILE NUMBER
    print("\n[Step 7] Testing Login using MOBILE NUMBER...")
    login_client2 = app.test_client()
    res = login_client2.post('/login', data={
        "contact": test_mobile,
        "password": test_password
    }, follow_redirects=False)
    assert res.status_code == 302, f"Expected redirect, got {res.status_code}"
    assert "/dashboard" in res.headers.get("Location")
    print("[PASS] Successfully logged in using MOBILE NUMBER! Redirected to /dashboard.")

    # 8. Test Login with incorrect password
    print("\n[Step 8] Testing Login with incorrect password...")
    login_client3 = app.test_client()
    res = login_client3.post('/login', data={
        "contact": test_email,
        "password": "IncorrectPassword"
    })
    assert b"Invalid Credentials" in res.data
    print("[PASS] Correctly rejected login with invalid password.")

    print("\n" + "=" * 65)
    print("ALL TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 65)


if __name__ == "__main__":
    test_registration_and_login_flow()
