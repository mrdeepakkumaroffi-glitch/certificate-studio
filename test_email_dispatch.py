import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Set UTF-8 encoding
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mailer
from app import app
from auth_jwt import generate_jwt_token


class TestEmailDispatch(unittest.TestCase):

    def test_email_validation(self):
        print("\n[Test 1] Testing Email Address Validation...")
        self.assertTrue(mailer.is_valid_email("student@university.edu"))
        self.assertTrue(mailer.is_valid_email("first.last+tag@sub.domain.com"))
        self.assertFalse(mailer.is_valid_email("not-an-email"))
        self.assertFalse(mailer.is_valid_email(""))
        self.assertFalse(mailer.is_valid_email(None))
        print("[PASS] Email regex validation verified.")

    @patch("smtplib.SMTP")
    def test_single_email_mock_send(self, mock_smtp_cls):
        print("\n[Test 2] Testing Single Certificate Email Sending with Attachment...")
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        test_pdf = b"%PDF-1.4 Mock PDF Binary Data"
        smtp_cfg = {
            "server": "smtp.gmail.com",
            "port": 587,
            "use_tls": True,
            "email": "sender@gmail.com",
            "password": "abcd efgh ijkl mnop",
            "sender_name": "Test Studio"
        }

        res = mailer.send_single_certificate_email(
            recipient_email="recipient@school.org",
            recipient_name="Vikram Patel",
            subject="Congratulations {Name}!",
            body_text="Hello {Name},\n\nYour certificate is attached.",
            pdf_bytes=test_pdf,
            pdf_filename="Certificate_Vikram.pdf",
            smtp_config=smtp_cfg
        )

        self.assertTrue(res["success"], f"Failed with: {res.get('error')}")
        self.assertTrue(mock_server.starttls.called)
        self.assertTrue(mock_server.login.called)
        self.assertTrue(mock_server.send_message.called)
        print("[PASS] Mock SMTP sent personalized message and attached PDF successfully.")

    @patch("mailer.get_default_smtp_config")
    @patch("mailer.send_single_certificate_email")
    def test_bulk_dispatch_flask_route(self, mock_send, mock_cfg):
        print("\n[Test 3] Testing Flask /dispatch-bulk-emails Endpoint...")
        mock_cfg.return_value = {
            "server": "smtp.gmail.com",
            "port": 587,
            "use_tls": True,
            "email": "test_sender@gmail.com",
            "password": "mockpassword1234",
            "sender_name": "Test Studio"
        }
        mock_send.return_value = {"success": True, "error": None}

        client = app.test_client()
        user = {"contact": "admin@studio.com", "name": "Admin User"}
        token = generate_jwt_token(user)
        client.set_cookie("access_token", token)

        # Set up session
        with client.session_transaction() as sess:
            sess["is_logged_in"] = True
            sess["user_contact"] = "admin@studio.com"
            sess["template_path"] = os.path.abspath("template.jpg")
            sess["excel_path"] = os.path.abspath("uploads/students.xlsx")
            sess["mappings"] = [{
                "field": "Name",
                "font": "Times New Roman",
                "size": 40,
                "color": "#000000",
                "x": 200, "y": 300, "w": 400, "h": 60
            }]

        # In uploads/students.xlsx, headers are: ['Name', 'College ', 'Age ', 'Price ']
        # Test missing email column error handling
        resp_err = client.post("/dispatch-bulk-emails", data={"email_column": "NonExistentColumn"})
        self.assertEqual(resp_err.status_code, 400)
        self.assertIn("not found", resp_err.get_json()["error"])
        print("[PASS] Handled non-existent email column correctly with HTTP 400.")


if __name__ == "__main__":
    unittest.main()
