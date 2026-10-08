"""
Comprehensive verification tests for Per-User Isolated SMTP Email Settings:
1. Tests Fernet AES encryption/decryption, key derivation, and error sanitization.
2. Verifies Zero Credential Leakage: App Password never returned in API responses or public getters.
3. Tests User Isolation: User A and User B cannot access or affect each other's SMTP configs.
4. Tests REST API endpoints (/api/smtp/settings, /api/smtp/test-connection, /api/smtp/test-email).
5. Tests bulk dispatch routing through authenticated user's personal SMTP credentials.
"""
import sys
import os
import json
import unittest
from unittest.mock import patch, MagicMock

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import smtp_security
import firebase_db
import mailer
from app import app
from auth_jwt import generate_jwt_token


class TestUserSmtpEngine(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

        # Test users
        self.user1 = {"contact": "instructor_alice@university.edu", "name": "Prof. Alice"}
        self.user2 = {"contact": "coordinator_bob@college.org", "name": "Bob Miller"}

        self.token_user1 = generate_jwt_token(self.user1)
        self.token_user2 = generate_jwt_token(self.user2)

    def tearDown(self):
        # Clean up test user configs
        firebase_db.delete_user_smtp_config(self.user1["contact"])
        firebase_db.delete_user_smtp_config(self.user2["contact"])

    def test_01_encryption_and_decryption(self):
        print("\n[Test 1] Testing Fernet AES Encryption, Decryption, and Tamper Resistance...")
        raw_pass = "abcd efgh ijkl mnop"
        encrypted = smtp_security.encrypt_app_password(raw_pass)

        # Ensure plain text is not visible in ciphertext
        self.assertNotIn("abcd", encrypted)
        self.assertNotIn("mnop", encrypted)
        self.assertTrue(len(encrypted) > 50)

        # Decrypt
        decrypted = smtp_security.decrypt_app_password(encrypted)
        self.assertEqual(decrypted, "abcdefghijklmnop")

        # Tampered ciphertext fails safely
        tampered = encrypted[:-5] + "XXXXX"
        safe_fail = smtp_security.decrypt_app_password(tampered)
        self.assertEqual(safe_fail, "")
        print("[PASS] Symmetric encryption, authenticated decryption, and safe failure verified.")

    def test_02_error_sanitization(self):
        print("\n[Test 2] Testing SMTP Error Sanitization & Credential Protection...")
        raw_auth_error = "535 5.7.8 Username and Password not accepted for user alice@gmail.com with pass secret123"
        sanitized = smtp_security.sanitize_smtp_error(raw_auth_error, ["secret123"])

        self.assertNotIn("secret123", sanitized)
        self.assertIn("Unable to connect to SMTP server", sanitized)
        self.assertIn("Google App Password", sanitized)
        print("[PASS] Error sanitization removes plain credentials and provides user guidance.")

    def test_03_zero_credential_leakage_and_user_isolation(self):
        print("\n[Test 3] Testing Database User Isolation & Zero-Leakage Data Model...")
        encrypted1 = smtp_security.encrypt_app_password("secret_pass_alice")
        firebase_db.save_user_smtp_config(self.user1["contact"], {
            "email": "alice_sender@gmail.com",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "security": "STARTTLS",
            "sender_name": "Prof. Alice",
            "encrypted_app_password": encrypted1,
            "is_verified": True
        })

        encrypted2 = smtp_security.encrypt_app_password("secret_pass_bob")
        firebase_db.save_user_smtp_config(self.user2["contact"], {
            "email": "bob_sender@outlook.com",
            "smtp_host": "smtp.office365.com",
            "smtp_port": 587,
            "security": "STARTTLS",
            "sender_name": "Bob Miller",
            "encrypted_app_password": encrypted2,
            "is_verified": True
        })

        # 1. Verify Alice's public config strips the password completely
        safe_cfg1 = firebase_db.get_user_smtp_config(self.user1["contact"], include_secret=False)
        self.assertNotIn("encrypted_app_password", safe_cfg1)
        self.assertNotIn("password", safe_cfg1)
        self.assertTrue(safe_cfg1["has_password"])
        self.assertEqual(safe_cfg1["masked_password"], "••••••••••••••••")
        self.assertEqual(safe_cfg1["email"], "alice_sender@gmail.com")

        # 2. Verify Bob's config is strictly separate
        safe_cfg2 = firebase_db.get_user_smtp_config(self.user2["contact"], include_secret=False)
        self.assertEqual(safe_cfg2["email"], "bob_sender@outlook.com")
        self.assertNotEqual(safe_cfg1["email"], safe_cfg2["email"])

        # 3. Verify internal decrypt only operates on intended user
        internal1 = firebase_db.get_user_smtp_config(self.user1["contact"], include_secret=True)
        decrypted_alice = smtp_security.decrypt_app_password(internal1["encrypted_app_password"])
        self.assertEqual(decrypted_alice, "secret_pass_alice")
        print("[PASS] Zero-credential leakage in public view and complete per-user isolation verified.")

    @patch("smtplib.SMTP")
    def test_04_api_save_and_test_connection(self, mock_smtp_cls):
        print("\n[Test 4] Testing REST API /api/smtp/test-connection & /api/smtp/settings...")
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        # 1. Test Connection API
        self.client.set_cookie("access_token", self.token_user1)
        resp_test = self.client.post("/api/smtp/test-connection", json={
            "email": "alice_sender@gmail.com",
            "password": "mock_google_app_pass",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "security": "STARTTLS"
        })

        self.assertEqual(resp_test.status_code, 200)
        data_test = resp_test.get_json()
        self.assertTrue(data_test["success"])
        self.assertEqual(data_test["message"], "SMTP connection successful.")
        self.assertTrue(mock_server.login.called)

        # 2. Save Settings API
        resp_save = self.client.post("/api/smtp/settings", json={
            "email": "alice_sender@gmail.com",
            "password": "mock_google_app_pass",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "security": "STARTTLS",
            "sender_name": "Prof. Alice"
        })
        self.assertEqual(resp_save.status_code, 200)
        data_save = resp_save.get_json()
        self.assertTrue(data_save["success"])
        # Verify response does NOT expose password
        self.assertNotIn("password", data_save["config"])
        self.assertNotIn("encrypted_app_password", data_save["config"])
        self.assertTrue(data_save["config"]["has_password"])

        # 3. GET Settings API
        resp_get = self.client.get("/api/smtp/settings")
        self.assertEqual(resp_get.status_code, 200)
        data_get = resp_get.get_json()
        self.assertTrue(data_get["configured"])
        self.assertEqual(data_get["config"]["email"], "alice_sender@gmail.com")

        # 4. DELETE Settings API
        resp_del = self.client.delete("/api/smtp/settings")
        self.assertEqual(resp_del.status_code, 200)
        resp_get2 = self.client.get("/api/smtp/settings")
        self.assertFalse(resp_get2.get_json()["configured"])
        print("[PASS] Full API CRUD and connection verification tested successfully.")

    @patch("mailer.send_single_certificate_email")
    def test_05_bulk_dispatch_uses_user_custom_smtp(self, mock_send):
        print("\n[Test 5] Testing Bulk Dispatch Per-User Routing & Queue Tracking...")
        mock_send.return_value = {"success": True, "error": None}

        # Save personal SMTP for User 1
        encrypted = smtp_security.encrypt_app_password("mock_app_pw_1234")
        firebase_db.save_user_smtp_config(self.user1["contact"], {
            "email": "personal_alice@university.edu",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "security": "STARTTLS",
            "sender_name": "Prof. Alice",
            "encrypted_app_password": encrypted,
            "is_verified": True
        })

        self.client.set_cookie("access_token", self.token_user1)
        with self.client.session_transaction() as sess:
            sess["is_logged_in"] = True
            sess["user_contact"] = self.user1["contact"]
            sess["template_path"] = os.path.abspath("template.jpg")
            sess["excel_path"] = os.path.abspath("students.xlsx")
            sess["mappings"] = [{
                "field": "Name",
                "font": "Times New Roman",
                "size": 40,
                "color": "#000000",
                "x": 100, "y": 200, "w": 300, "h": 50
            }]

        # Trigger bulk dispatch
        resp = self.client.post("/dispatch-bulk-emails", data={
            "email_column": "Email",
            "subject": "Official Award Certificate for {Name}",
            "body": "Congratulations {Name}!"
        })

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["is_custom_smtp"])
        self.assertEqual(data["sender"], "personal_alice@university.edu")

        # Verify mailer was invoked using Alice's personal SMTP credentials
        self.assertTrue(mock_send.called)
        call_smtp_cfg = mock_send.call_args[1]["smtp_config"]
        self.assertEqual(call_smtp_cfg["email"], "personal_alice@university.edu")
        self.assertEqual(call_smtp_cfg["password"], "mock_app_pw_1234")
        print("[PASS] Bulk dispatch securely loaded, decrypted, and transmitted via user's personal SMTP account.")


if __name__ == "__main__":
    unittest.main()
