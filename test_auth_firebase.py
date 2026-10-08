"""
Self-contained verification script for JWT Authentication & Firebase Database Integration.
"""
import sys
import os

# Set UTF-8 encoding for standard output
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure local imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth_jwt import (
    hash_password,
    verify_password,
    generate_jwt_token,
    decode_jwt_token
)
import firebase_db
from app import app


def run_tests():
    print("=" * 60)
    print("Starting JWT & Firebase Integration Verification")
    print("=" * 60)

    # 1. Test Password Hashing
    print("\n[Test 1] Testing Password Hashing & Verification...")
    raw_pass = "SecurePass@123"
    hashed = hash_password(raw_pass)
    assert hashed != raw_pass, "Password should not be plaintext"
    assert verify_password(hashed, raw_pass) is True, "Password verification failed"
    assert verify_password(hashed, "WrongPass") is False, "Wrong password unexpectedly passed"
    print("[PASS] Password hashing and verification passed.")

    # 2. Test Firebase Database User Operations
    print("\n[Test 2] Testing Firebase User Creation & Retrieval...")
    test_contact = "test_instructor@studio.com"
    test_name = "Dr. Alice Morgan"
    
    user = firebase_db.create_user(contact=test_contact, name=test_name, password=raw_pass)
    assert user["contact"] == test_contact
    assert user["name"] == test_name
    print(f"[PASS] User created in database: {user['name']} ({user['contact']})")

    # Verify retrieval
    retrieved = firebase_db.get_user_by_contact(test_contact)
    assert retrieved is not None, "Failed to retrieve user from database"
    assert retrieved["name"] == test_name
    print("[PASS] User retrieved successfully from database.")

    # Verify credentials
    verified_user = firebase_db.verify_user_credentials(test_contact, raw_pass)
    assert verified_user is not None, "Failed to verify credentials"
    assert firebase_db.verify_user_credentials(test_contact, "WrongPass") is None, "Wrong credentials passed"
    print("[PASS] Credential verification against database passed.")

    # 3. Test JWT Token Generation and Decoding
    print("\n[Test 3] Testing JWT Issuance and Validation...")
    token = generate_jwt_token(user, expires_in_hours=12)
    assert isinstance(token, str) and len(token) > 20, "Invalid token format"
    print(f"[PASS] JWT Token generated: {token[:25]}...{token[-10:]}")

    payload = decode_jwt_token(token)
    assert payload is not None, "Token decoding failed"
    assert payload["sub"] == test_contact, f"Expected subject {test_contact}, got {payload.get('sub')}"
    assert payload["name"] == test_name, f"Expected name {test_name}, got {payload.get('name')}"
    print("[PASS] JWT Token successfully decoded and validated.")

    # 4. Test Certificate Generation History Tracking
    print("\n[Test 4] Testing Generation History in Firebase...")
    record_id = firebase_db.save_generation_record(test_contact, {
        "excel_name": "annual_awards.xlsx",
        "template_name": "diploma_template.jpg",
        "total_certificates": 45,
        "mappings_count": 3,
        "pdf_filename": "Generated_Certificates.pdf"
    })
    print(f"[PASS] Generation record saved in Firebase with ID: {record_id}")

    generations = firebase_db.get_user_generations(test_contact)
    assert len(generations) >= 1, "Expected at least 1 generation record"
    assert generations[0]["total_certificates"] == 45
    print(f"[PASS] Generation history retrieved: {len(generations)} record(s) found.")

    stats = firebase_db.get_user_stats(test_contact)
    assert stats["total_certificates"] >= 45
    assert stats["total_batches"] >= 1
    print(f"[PASS] User stats calculated: {stats['total_certificates']} certificates across {stats['total_batches']} batch(es). Mode: {stats['db_mode']}")

    # 5. Test Flask App HTTP Endpoints via Test Client
    print("\n[Test 5] Testing Flask JWT-Protected Routes...")
    client = app.test_client()

    # Unauthenticated access to /dashboard should redirect to /login
    unauth_resp = client.get("/dashboard", follow_redirects=False)
    assert unauth_resp.status_code == 302, f"Expected 302 redirect, got {unauth_resp.status_code}"
    assert "/login" in unauth_resp.headers.get("Location", "")
    print("[PASS] Unauthenticated request correctly blocked and redirected to /login.")

    # Authenticated access with JWT cookie
    client.set_cookie("access_token", token)
    auth_resp = client.get("/dashboard")
    assert auth_resp.status_code == 200, f"Expected 200 OK, got {auth_resp.status_code}"
    assert b"Dashboard Overview" in auth_resp.data
    assert b"Dr. Alice Morgan" in auth_resp.data
    print("[PASS] JWT-authenticated request succeeded for /dashboard.")

    # Programmatic API endpoint with Bearer header
    api_resp = client.get("/api/user/status", headers={"Authorization": f"Bearer {token}"})
    assert api_resp.status_code == 200
    json_data = api_resp.get_json()
    assert json_data["status"] == "authenticated"
    assert json_data["user"]["contact"] == test_contact
    print(f"[PASS] API endpoint /api/user/status validated with Bearer token.")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! JWT & Firebase are fully operational.")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
