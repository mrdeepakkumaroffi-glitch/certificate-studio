import os
import re
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from dotenv import load_dotenv

import smtp_security

load_dotenv()


def normalize_smtp_config(smtp_config: dict) -> dict:
    """
    Standardizes SMTP configuration keys across system defaults and per-user settings.
    Supports both legacy keys ('server', 'use_tls') and new schema keys ('smtp_host', 'security').
    """
    if not smtp_config:
        return get_default_smtp_config()

    host = (smtp_config.get("smtp_host") or smtp_config.get("server") or "smtp.gmail.com").strip()
    try:
        port = int(smtp_config.get("smtp_port") or smtp_config.get("port") or 587)
    except (ValueError, TypeError):
        port = 587

    # Determine security encryption mode
    sec = smtp_config.get("security")
    if sec:
        security_mode = str(sec).strip().upper()
    elif smtp_config.get("use_tls") is not None:
        security_mode = "STARTTLS" if smtp_config.get("use_tls") else ("SSL/TLS" if port == 465 else "NONE")
    elif port == 465:
        security_mode = "SSL/TLS"
    else:
        security_mode = "STARTTLS"

    raw_pass = smtp_config.get("password") or ""
    clean_pass = str(raw_pass).strip().replace(" ", "")

    return {
        "server": host,
        "smtp_host": host,
        "port": port,
        "smtp_port": port,
        "security": security_mode,
        "use_tls": (security_mode == "STARTTLS"),
        "email": str(smtp_config.get("email") or "").strip().lower(),
        "password": clean_pass,
        "sender_name": str(smtp_config.get("sender_name") or "Certificate Studio").strip(),
        "is_custom": bool(smtp_config.get("is_custom", False))
    }


def get_default_smtp_config():
    """Returns default system fallback SMTP configuration from environment variables (.env)."""
    load_dotenv(override=True)
    raw_pass = os.getenv("SMTP_PASSWORD", "").strip()
    clean_pass = raw_pass.replace(" ", "")
    return normalize_smtp_config({
        "server": os.getenv("SMTP_SERVER", "smtp.gmail.com").strip(),
        "port": int(os.getenv("SMTP_PORT", 587)),
        "use_tls": os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes"),
        "email": os.getenv("SMTP_EMAIL", "").strip(),
        "password": clean_pass,
        "sender_name": os.getenv("SMTP_SENDER_NAME", "Certificate Studio").strip(),
        "is_custom": False
    })


def get_user_or_default_smtp_config(contact: str = None) -> tuple[dict, bool]:
    """
    Retrieves the authenticated user's isolated SMTP configuration if configured and verified.
    Securely decrypts the App Password in-memory solely for this session.
    Falls back to system default (.env) if user has not configured custom SMTP.
    Returns: (smtp_config_dict, is_custom_user_config: bool)
    """
    if contact:
        try:
            import firebase_db
            user_smtp = firebase_db.get_user_smtp_config(contact, include_secret=True)
            if user_smtp and user_smtp.get("encrypted_app_password"):
                cipher = user_smtp.get("encrypted_app_password")
                decrypted = smtp_security.decrypt_app_password(cipher)
                if decrypted:
                    cfg = dict(user_smtp)
                    cfg["password"] = decrypted
                    cfg["is_custom"] = True
                    return normalize_smtp_config(cfg), True
        except Exception:
            pass

    return get_default_smtp_config(), False


def is_valid_email(email_str: str) -> bool:
    """Validates an email address format."""
    if not email_str:
        return False
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, str(email_str).strip()))


def verify_smtp_credentials(smtp_config: dict) -> dict:
    """
    Performs a lightweight, real-time SMTP handshake and login authentication check.
    Does NOT send any email.
    Returns: {'success': bool, 'message': str, 'error': str}
    """
    cfg = normalize_smtp_config(smtp_config)
    sender_email = cfg.get("email", "").strip()
    sender_pass = cfg.get("password", "").strip()
    host = cfg.get("server", "smtp.gmail.com").strip()
    port = cfg.get("port", 587)
    security = cfg.get("security", "STARTTLS")

    if not sender_email or not sender_pass:
        return {
            "success": False,
            "error": "Email address and App Password cannot be empty."
        }

    if not is_valid_email(sender_email):
        return {
            "success": False,
            "error": f"Invalid email format: '{sender_email}'"
        }

    server = None
    try:
        if security == "SSL/TLS" or port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if security == "STARTTLS":
                server.starttls()

        server.login(sender_email, sender_pass)
        try:
            server.quit()
        except Exception:
            pass
        return {
            "success": True,
            "message": "SMTP connection successful."
        }
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "error": "Unable to connect to SMTP server. Please verify your SMTP settings and App Password."
        }
    except Exception as e:
        sanitized = smtp_security.sanitize_smtp_error(str(e), [sender_pass])
        return {
            "success": False,
            "error": sanitized
        }


def send_single_certificate_email(
    recipient_email: str,
    recipient_name: str,
    subject: str,
    body_text: str,
    pdf_bytes: bytes,
    pdf_filename: str,
    smtp_config: dict = None
) -> dict:
    """
    Sends an individual certificate attached as a PDF to the specified recipient email using SMTP.
    Supports STARTTLS, SSL/TLS, and plain SMTP with user credentials.
    Returns a dict with {'success': bool, 'error': str}.
    """
    cfg = normalize_smtp_config(smtp_config) if smtp_config else get_default_smtp_config()

    sender_email = cfg.get("email", "").strip()
    sender_pass = cfg.get("password", "").strip()
    sender_name = cfg.get("sender_name", "Certificate Studio").strip()
    smtp_server = cfg.get("server", "smtp.gmail.com").strip()
    smtp_port = cfg.get("port", 587)
    security = cfg.get("security", "STARTTLS")

    if not sender_email or not sender_pass:
        return {
            "success": False,
            "error": "Sender email or App Password is not configured. Please verify your SMTP settings."
        }

    recipient_email = recipient_email.strip()
    if not is_valid_email(recipient_email):
        return {
            "success": False,
            "error": f"Invalid recipient email address: '{recipient_email}'"
        }

    # Personalize Subject and Body
    personalized_subject = subject.replace("{Name}", recipient_name).replace("{name}", recipient_name)
    personalized_body = body_text.replace("{Name}", recipient_name).replace("{name}", recipient_name)

    # Build MIME Message
    msg = MIMEMultipart("mixed")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = personalized_subject

    # HTML Body with clean typography
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f8fafc; color: #1e293b; padding: 20px; }}
            .email-card {{ background: #ffffff; border-radius: 12px; padding: 30px; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            .brand-header {{ font-size: 18px; font-weight: 800; color: #4f46e5; margin-bottom: 20px; border-bottom: 2px solid #e0e7ff; padding-bottom: 12px; }}
            .message-text {{ font-size: 15px; line-height: 1.6; color: #334155; white-space: pre-line; margin-bottom: 25px; }}
            .attachment-pill {{ background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; padding: 10px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; display: inline-block; }}
            .footer {{ font-size: 12px; color: #94a3b8; margin-top: 30px; text-align: center; border-top: 1px solid #f1f5f9; padding-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="email-card">
            <div class="brand-header">📜 Certificate of Achievement</div>
            <div class="message-text">{personalized_body}</div>
            <div class="attachment-pill">📎 Attached Certificate: {pdf_filename}</div>
            <div class="footer">Sent securely via {sender_name} • Powered by Certificate Studio</div>
        </div>
    </body>
    </html>
    """

    alt_part = MIMEMultipart("alternative")
    alt_part.attach(MIMEText(personalized_body, "plain", "utf-8"))
    alt_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt_part)

    # Attach PDF Certificate
    try:
        pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf_attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(pdf_attachment)
    except Exception as e:
        return {"success": False, "error": f"Failed to attach PDF: {str(e)}"}

    # Transmit via SMTP
    server = None
    try:
        if security == "SSL/TLS" or smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
            if security == "STARTTLS":
                server.starttls()

        server.login(sender_email, sender_pass)
        server.send_message(msg)
        try:
            server.quit()
        except Exception:
            pass
        return {"success": True, "error": None}
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "error": "Authentication failed. For Gmail, make sure you are using a 16-character Google App Password (not your regular account password) with 2-Step Verification enabled."
        }
    except Exception as e:
        sanitized = smtp_security.sanitize_smtp_error(str(e), [sender_pass])
        return {"success": False, "error": sanitized}


def test_smtp_connection(smtp_config: dict, test_recipient: str = None) -> dict:
    """Verifies SMTP credentials and sends a test email if a recipient is provided."""
    cfg = normalize_smtp_config(smtp_config)
    sender_email = cfg.get("email", "").strip()
    target = test_recipient.strip() if test_recipient else sender_email

    # Create dummy sample PDF for verification
    dummy_pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\nxref\n0 4\n0000000000 65535 f\n0000000010 00000 n\n0000000053 00000 n\n0000000102 00000 n\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n149\n%%EOF"

    return send_single_certificate_email(
        recipient_email=target,
        recipient_name="Studio Administrator",
        subject="Test Certificate Email - Configuration Verified",
        body_text="Hello!\n\nThis is a test certificate dispatch to verify your SMTP configuration.\nYour credentials are valid and ready for bulk dispatch.",
        pdf_bytes=dummy_pdf,
        pdf_filename="Test_Certificate.pdf",
        smtp_config=cfg
    )


def send_otp_email(
    recipient_email: str,
    recipient_name: str,
    otp_code: str,
    smtp_config: dict = None
) -> dict:
    """
    Sends a professional, branded 6-digit OTP email for account verification using Gmail SMTP.
    Returns {'success': bool, 'error': str}.
    """
    if not smtp_config:
        smtp_config = get_default_smtp_config()

    sender_email = smtp_config.get("email", "").strip()
    sender_pass = smtp_config.get("password", "").strip()
    sender_name = smtp_config.get("sender_name", "Certificate Studio").strip()
    smtp_server = smtp_config.get("server", "smtp.gmail.com").strip()
    smtp_port = int(smtp_config.get("port", 587))
    use_tls = smtp_config.get("use_tls", True)

    if not sender_email or not sender_pass:
        return {
            "success": False,
            "error": "Sender email or Google App Password is not configured in .env file."
        }

    recipient_email = recipient_email.strip()
    if not is_valid_email(recipient_email):
        return {
            "success": False,
            "error": f"Invalid recipient email address: '{recipient_email}'"
        }

    subject = f"🔐 Your Certificate Studio Verification Code: {otp_code}"
    
    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background-color: #0b0f19;
                color: #e2e8f0;
                margin: 0;
                padding: 30px 15px;
            }}
            .card {{
                max-width: 520px;
                margin: 0 auto;
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 18px;
                padding: 36px 30px;
                box-shadow: 0 15px 35px rgba(0, 0, 0, 0.5);
            }}
            .brand-badge {{
                display: inline-block;
                background: linear-gradient(135deg, #ec4899 0%, #8b5cf6 100%);
                color: #ffffff;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                padding: 6px 14px;
                border-radius: 50px;
                margin-bottom: 20px;
            }}
            h2 {{
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
                margin-top: 0;
                margin-bottom: 12px;
            }}
            p {{
                font-size: 14px;
                line-height: 1.6;
                color: #94a3b8;
                margin-bottom: 20px;
            }}
            .otp-box {{
                background: rgba(139, 92, 246, 0.08);
                border: 2px dashed #8b5cf6;
                border-radius: 14px;
                padding: 20px;
                text-align: center;
                margin: 25px 0;
            }}
            .otp-code {{
                font-family: 'Courier New', Courier, monospace;
                font-size: 34px;
                font-weight: 800;
                letter-spacing: 10px;
                color: #38bdf8;
                display: inline-block;
            }}
            .expiry-note {{
                font-size: 12px;
                color: #a855f7;
                margin-top: 8px;
                font-weight: 600;
            }}
            .security-notice {{
                background: #1e293b;
                border-left: 4px solid #f59e0b;
                padding: 12px 14px;
                border-radius: 8px;
                font-size: 12px;
                color: #cbd5e1;
                margin-top: 24px;
                line-height: 1.5;
            }}
            .footer {{
                font-size: 11px;
                color: #64748b;
                text-align: center;
                margin-top: 30px;
                padding-top: 18px;
                border-top: 1px solid #1f2937;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="brand-badge">Certificate Studio Pro</div>
            <h2>Verify Your Email Address</h2>
            <p>Hello <strong style="color: #f8fafc;">{recipient_name}</strong>,</p>
            <p>Welcome to <strong>Certificate Studio</strong>. To complete your account registration and secure your profile, please enter the following 6-digit verification code:</p>
            
            <div class="otp-box">
                <div class="otp-code">{otp_code}</div>
                <div class="expiry-note">⏱️ Code valid for 10 minutes</div>
            </div>

            <p style="margin-bottom: 0;">Once verified, your account will be activated with instant access to the professional certificate design & batch generation studio.</p>

            <div class="security-notice">
                ⚠️ <strong>Security Notice:</strong> Never share this verification code with anyone. Certificate Studio staff will never ask for your code or password.
            </div>

            <div class="footer">
                © 2026 Certificate Studio • Sent securely via Gmail TLS • Automated Notification
            </div>
        </div>
    </body>
    </html>
    """

    plain_body = f"""Hello {recipient_name},

Your Certificate Studio verification code is: {otp_code}

This code is valid for 10 minutes. Enter this code on the registration page to verify your email address.

If you did not request this code, you can safely ignore this email.

Best regards,
Certificate Studio Team
"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
            if use_tls:
                server.starttls()

        server.login(sender_email, sender_pass)
        server.send_message(msg)
        server.quit()
        return {"success": True, "error": None}
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "error": "Authentication failed with Gmail SMTP. Check SMTP_EMAIL and SMTP_PASSWORD (Google App Password) in your .env file."
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to send email via SMTP: {str(e)}"}


def send_password_reset_otp_email(
    recipient_email: str,
    recipient_name: str,
    otp_code: str,
    smtp_config: dict = None
) -> dict:
    """
    Sends a high-security, branded 6-digit OTP email specifically for Password Reset via Gmail SMTP.
    Returns {'success': bool, 'error': str}.
    """
    if not smtp_config:
        smtp_config = get_default_smtp_config()

    sender_email = smtp_config.get("email", "").strip()
    sender_pass = smtp_config.get("password", "").strip()
    sender_name = smtp_config.get("sender_name", "Certificate Studio").strip()
    smtp_server = smtp_config.get("server", "smtp.gmail.com").strip()
    smtp_port = int(smtp_config.get("port", 587))
    use_tls = smtp_config.get("use_tls", True)

    if not sender_email or not sender_pass:
        return {
            "success": False,
            "error": "Sender email or Google App Password is not configured in .env file."
        }

    recipient_email = recipient_email.strip()
    if not is_valid_email(recipient_email):
        return {
            "success": False,
            "error": f"Invalid recipient email address: '{recipient_email}'"
        }

    subject = f"🔑 Password Reset Code: {otp_code} - Certificate Studio"

    html_body = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                background-color: #0b0f19;
                color: #e2e8f0;
                margin: 0;
                padding: 30px 15px;
            }}
            .card {{
                max-width: 520px;
                margin: 0 auto;
                background: #111827;
                border: 1px solid #1f2937;
                border-radius: 18px;
                padding: 36px 30px;
                box-shadow: 0 15px 35px rgba(0, 0, 0, 0.5);
            }}
            .brand-badge {{
                display: inline-block;
                background: linear-gradient(135deg, #f43f5e 0%, #a855f7 100%);
                color: #ffffff;
                font-size: 11px;
                font-weight: 800;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                padding: 6px 14px;
                border-radius: 50px;
                margin-bottom: 20px;
            }}
            h2 {{
                color: #ffffff;
                font-size: 22px;
                font-weight: 800;
                margin-top: 0;
                margin-bottom: 12px;
            }}
            p {{
                font-size: 14px;
                line-height: 1.6;
                color: #94a3b8;
                margin-bottom: 20px;
            }}
            .otp-box {{
                background: rgba(244, 63, 94, 0.08);
                border: 2px dashed #f43f5e;
                border-radius: 14px;
                padding: 20px;
                text-align: center;
                margin: 25px 0;
            }}
            .otp-code {{
                font-family: 'Courier New', Courier, monospace;
                font-size: 34px;
                font-weight: 800;
                letter-spacing: 10px;
                color: #fb7185;
                display: inline-block;
            }}
            .expiry-note {{
                font-size: 12px;
                color: #cbd5e1;
                margin-top: 8px;
                font-weight: 600;
            }}
            .security-notice {{
                background: #1e293b;
                border-left: 4px solid #ef4444;
                padding: 14px 16px;
                border-radius: 8px;
                font-size: 12px;
                color: #cbd5e1;
                margin-top: 24px;
                line-height: 1.5;
            }}
            .footer {{
                font-size: 11px;
                color: #64748b;
                text-align: center;
                margin-top: 30px;
                padding-top: 18px;
                border-top: 1px solid #1f2937;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="brand-badge">Security • Password Reset</div>
            <h2>Password Reset Verification</h2>
            <p>Hello <strong style="color: #f8fafc;">{recipient_name}</strong>,</p>
            <p>We received a request to reset the password associated with your <strong>Certificate Studio</strong> account. Please use the 6-digit verification code below to authorize this change:</p>
            
            <div class="otp-box">
                <div class="otp-code">{otp_code}</div>
                <div class="expiry-note">⏱️ Code expires in 10 minutes</div>
            </div>

            <p style="margin-bottom: 0;">Once entered, you will be able to create a new password and regain access to your certificate design projects.</p>

            <div class="security-notice">
                🛡️ <strong>Security Alert:</strong> If you did not request a password reset, please ignore this email. Your current password remains safe and unchanged. Never disclose this code to anyone.
            </div>

            <div class="footer">
                © 2026 Certificate Studio • Sent securely via Gmail TLS • Automated Security Dispatch
            </div>
        </div>
    </body>
    </html>
    """

    plain_body = f"""Hello {recipient_name},

We received a request to reset the password for your Certificate Studio account.

Your password reset verification code is: {otp_code}

This code is valid for 10 minutes. Enter this code on the password reset screen to set a new password.

If you did not request a password reset, please disregard this email. Your account remains completely secure.

Best regards,
Certificate Studio Security Team
"""

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = recipient_email
    msg["Subject"] = subject

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=20)
            if use_tls:
                server.starttls()

        server.login(sender_email, sender_pass)
        server.send_message(msg)
        server.quit()
        return {"success": True, "error": None}
    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "error": "Authentication failed with Gmail SMTP. Check SMTP_EMAIL and SMTP_PASSWORD in your .env file."
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to send email via SMTP: {str(e)}"}


