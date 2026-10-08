import os
import datetime
import jwt
from functools import wraps
from flask import request, redirect, url_for, session, g, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "certificate_studio_jwt_super_secure_key_default")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", 24))


def hash_password(password: str) -> str:
    """Hashes a plain text password using Werkzeug's secure hash."""
    return generate_password_hash(password)


def verify_password(stored_hash: str, plain_password: str) -> bool:
    """Verifies a plain password against the stored password hash."""
    if not stored_hash or not plain_password:
        return False
    return check_password_hash(stored_hash, plain_password)


def generate_jwt_token(user_data: dict, expires_in_hours: int = None) -> str:
    """Generates a signed JWT token containing user identity and metadata."""
    if expires_in_hours is None:
        expires_in_hours = JWT_EXPIRATION_HOURS

    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": user_data.get("contact"),
        "contact": user_data.get("contact"),
        "name": user_data.get("name"),
        "tier": user_data.get("tier", "Pro"),
        "iat": now,
        "exp": now + datetime.timedelta(hours=expires_in_hours)
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def decode_jwt_token(token: str) -> dict:
    """Decodes and validates a JWT token. Returns payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


def get_token_from_request():
    """Extracts JWT token from Authorization header, access_token cookie, or Flask session."""
    # 1. Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    # 2. Check HTTP-only cookie
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token.strip()

    # 3. Check Flask session fallback
    session_token = session.get("jwt_token")
    if session_token:
        return session_token.strip()

    return None


def jwt_required(f):
    """
    Decorator that protects Flask routes with JWT authentication.
    Injects `current_user` into Flask's `g` context.
    Redirects unauthenticated browser requests to /login,
    or returns 401 JSON for API requests.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = get_token_from_request()

        if not token:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Missing authentication token"}), 401
            session.clear()
            return redirect(url_for("login"))

        payload = decode_jwt_token(token)
        if not payload:
            if request.is_json or request.path.startswith("/api/"):
                return jsonify({"error": "Invalid or expired token"}), 401
            session.clear()
            return redirect(url_for("login", error="Session expired. Please log in again."))

        # Attach user info to Flask `g` context
        g.current_user = payload
        g.user_contact = payload.get("contact")
        g.user_name = payload.get("name")
        return f(*args, **kwargs)

    return decorated_function
