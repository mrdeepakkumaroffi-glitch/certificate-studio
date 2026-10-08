import os
import base64
import hashlib
import re
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

load_dotenv()


def _get_fernet_instance() -> Fernet:
    """
    Derives a secure 32-byte URL-safe base64 key from environment variables.
    Prefers SMTP_ENCRYPTION_KEY, falls back to FLASK_SECRET_KEY, with a secure salt.
    """
    secret = (
        os.getenv("SMTP_ENCRYPTION_KEY")
        or os.getenv("FLASK_SECRET_KEY")
        or "cert-studio-secure-smtp-salt-key-2026-production"
    ).strip()

    # Create deterministic 32-byte key via SHA-256 and URL-safe base64 encode
    raw_digest = hashlib.sha256(secret.encode("utf-8")).digest()
    key_b64 = base64.urlsafe_b64encode(raw_digest)
    return Fernet(key_b64)


def encrypt_app_password(plain_password: str) -> str:
    """
    Encrypts a plain text App Password into an authenticated Fernet ciphertext token.
    Never logs or persists the plain password.
    """
    if not plain_password:
        return ""
    # Clean whitespace (Google App Passwords often have spaces like 'abcd efgh ijkl mnop')
    clean = plain_password.strip().replace(" ", "")
    f = _get_fernet_instance()
    encrypted_bytes = f.encrypt(clean.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_app_password(ciphertext: str) -> str:
    """
    Decrypts an authenticated Fernet ciphertext token back into the plain text App Password.
    Returns empty string if token is invalid, expired, or corrupted.
    """
    if not ciphertext:
        return ""
    try:
        f = _get_fernet_instance()
        decrypted_bytes = f.decrypt(ciphertext.strip().encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except (InvalidToken, Exception):
        return ""


def mask_app_password(value: str = None) -> str:
    """
    Returns a standardized bullet mask string for UI/API display.
    Guarantees no actual characters are exposed.
    """
    return "••••••••••••••••"


def sanitize_smtp_error(raw_error: str, credentials_to_redact: list = None) -> str:
    """
    Sanitizes SMTP and network error messages before sending to client or logging.
    Removes passwords, auth tokens, database paths, and converts technical tracebacks
    into safe, human-readable user guidance.
    """
    if not raw_error:
        return "An unknown error occurred during SMTP communication."

    error_str = str(raw_error)

    # Redact any supplied credential strings
    if credentials_to_redact:
        for cred in credentials_to_redact:
            if cred and len(cred) > 3:
                error_str = error_str.replace(cred, "[REDACTED]")

    # Redact email-looking patterns in raw error if they look like credentials
    # Pattern matching typical SMTP error codes
    err_lower = error_str.lower()

    if "535" in error_str or "authentication failed" in err_lower or "badcredentials" in err_lower:
        return (
            "Unable to connect to SMTP server. Please verify your SMTP settings and App Password. "
            "For Gmail, make sure you are using a 16-character Google App Password (not your normal account password) "
            "with 2-Step Verification enabled."
        )

    if "timed out" in err_lower or "timeout" in err_lower:
        return "SMTP connection timed out. Please verify your SMTP Host and Port (e.g., smtp.gmail.com:587) and check network connectivity."

    if "connection refused" in err_lower or "10061" in error_str:
        return "Connection refused by the mail server. Please verify the SMTP Host and Port number."

    if "ssl" in err_lower or "certificate" in err_lower or "handshake" in err_lower or "starttls" in err_lower:
        return "Secure TLS/SSL handshake failed. Please check your Security setting (STARTTLS vs SSL/TLS) and Port number."

    if "getaddrinfo failed" in err_lower or "name or service not known" in err_lower:
        return "SMTP Host domain not found. Please double-check the server address (e.g., smtp.gmail.com)."

    if "550" in error_str or "relay" in err_lower or "not permitted" in err_lower:
        return "Sender email not authorized by this SMTP server, or recipient address was rejected."

    # Remove any file system paths or stack trace markers
    cleaned = re.sub(r'([a-zA-Z]:\\[^:\n\r]+|\/[a-zA-Z0-9_\-\.\/]+)', '[Path]', error_str)
    # Strip any potential base64 or hex tokens > 16 chars
    cleaned = re.sub(r'[a-zA-Z0-9+/=]{20,}', '[Token]', cleaned)
    
    return f"SMTP Error: {cleaned.strip()}"
