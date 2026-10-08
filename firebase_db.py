import os
import json
import datetime
from dotenv import load_dotenv
from auth_jwt import hash_password, verify_password

load_dotenv()

CREDENTIALS_PATH = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase_credentials.json")
LOCAL_STORE_PATH = "firebase_local_store.json"

_firestore_client = None
_is_live_firestore = False

# Attempt to initialize Firebase Admin SDK
try:
    if os.path.exists(CREDENTIALS_PATH):
        # Validate that the file is not a placeholder example
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            raw_content = f.read()

        if "your-firebase-project-id" in raw_content or "...YOUR_KEY..." in raw_content:
            print(f"[Firebase Notice] '{CREDENTIALS_PATH}' contains placeholder values.")
            print("[Firebase Notice] Please replace it with your real private key from Firebase Console.")
            print("[Firebase Notice] Operating with persistent local database fallback.")
            _firestore_client = None
            _is_live_firestore = False
        else:
            import firebase_admin
            from firebase_admin import credentials, firestore

            # Check if already initialized
            if not firebase_admin._apps:
                cred = credentials.Certificate(CREDENTIALS_PATH)
                firebase_admin.initialize_app(cred)
            _firestore_client = firestore.client()
            _is_live_firestore = True
            print(f"[Firebase] Successfully connected to Google Cloud Firestore using '{CREDENTIALS_PATH}'.")
    else:
        print(f"[Firebase Notice] '{CREDENTIALS_PATH}' not found.")
        print("[Firebase Notice] Operating with persistent local database fallback.")
        print("[Firebase Notice] To connect to live Cloud Firestore: Download your service account key from Firebase Console and save it as 'firebase_credentials.json'.")
except Exception as e:
    print(f"[Firebase Warning] Could not initialize Firebase Admin SDK: {e}")
    print("[Firebase Warning] Falling back to local persistent store.")
    _firestore_client = None
    _is_live_firestore = False


def is_using_live_firebase() -> bool:
    """Returns True if connected to live Google Cloud Firestore, False if using local fallback."""
    return _is_live_firestore


# -------------------------------------------------------------
# Local Persistent Store Helpers (Fallback when credentials missing)
# -------------------------------------------------------------
def _load_local_store() -> dict:
    if not os.path.exists(LOCAL_STORE_PATH):
        return {"users": {}, "generations": [], "smtp_configs": {}}
    try:
        with open(LOCAL_STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "smtp_configs" not in data:
                data["smtp_configs"] = {}
            return data
    except Exception:
        return {"users": {}, "generations": [], "smtp_configs": {}}


def _save_local_store(data: dict):
    with open(LOCAL_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# -------------------------------------------------------------
# User Database Operations
# -------------------------------------------------------------
def create_user(contact: str, name: str, password: str, avatar: str = "", mobile: str = "", email: str = "") -> dict:
    """
    Creates a new user record in Firebase Firestore (or fallback).
    Supports name, mobile, email, and password.
    Passwords are automatically hashed securely with Werkzeug before storage.
    """
    contact = contact.strip().lower()
    
    # Infer email/mobile if not explicitly passed
    if not email and "@" in contact:
        email = contact
    if not mobile and contact.replace("+", "").replace("-", "").isdigit():
        mobile = contact

    email_clean = email.strip().lower() if email else contact
    mobile_clean = mobile.strip() if mobile else ""

    # Primary key document identifier: use email if available, else contact
    doc_key = email_clean if email_clean else contact

    user_doc = {
        "contact": doc_key,
        "name": name.strip(),
        "email": email_clean,
        "mobile": mobile_clean,
        "password_hash": hash_password(password),
        "avatar": avatar,
        "tier": "Pro",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "last_login": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    if _is_live_firestore and _firestore_client:
        _firestore_client.collection("users").document(doc_key).set(user_doc)
    else:
        data = _load_local_store()
        data["users"][doc_key] = user_doc
        if mobile_clean and mobile_clean != doc_key:
            data["users"][mobile_clean] = user_doc
        _save_local_store(data)

    return user_doc


def get_user_by_contact(contact: str) -> dict:
    """
    Retrieves a user document by either their email ID OR mobile number.
    Checks document ID first, then queries by email and mobile fields.
    Guarantees 'doc_id', 'contact', 'email', 'mobile' are always attached.
    """
    if not contact:
        return None
    raw_ident = str(contact).strip()
    lower_ident = raw_ident.lower()

    def _enrich(doc_id: str, data: dict) -> dict:
        if not isinstance(data, dict):
            return None
        data["doc_id"] = doc_id
        if not data.get("contact"):
            data["contact"] = doc_id
        if not data.get("email") and "@" in doc_id:
            data["email"] = doc_id
        if not data.get("mobile") and doc_id.replace("+", "").replace("-", "").isdigit():
            data["mobile"] = doc_id
        return data

    if _is_live_firestore and _firestore_client:
        # 1. Direct document ID lookup
        doc_ref = _firestore_client.collection("users").document(lower_ident)
        doc = doc_ref.get()
        if doc.exists:
            return _enrich(doc.id, doc.to_dict())

        # If raw identifier differs in case
        if raw_ident != lower_ident:
            doc_ref2 = _firestore_client.collection("users").document(raw_ident)
            doc2 = doc_ref2.get()
            if doc2.exists:
                return _enrich(doc2.id, doc2.to_dict())

        # 2. Query where email == lower_ident
        docs = _firestore_client.collection("users").where("email", "==", lower_ident).limit(1).stream()
        for d in docs:
            return _enrich(d.id, d.to_dict())

        # 3. Query where mobile == raw_ident
        docs = _firestore_client.collection("users").where("mobile", "==", raw_ident).limit(1).stream()
        for d in docs:
            return _enrich(d.id, d.to_dict())

        # 4. Query where contact == lower_ident
        docs = _firestore_client.collection("users").where("contact", "==", lower_ident).limit(1).stream()
        for d in docs:
            return _enrich(d.id, d.to_dict())

        # 5. Local store fallback & auto-sync to Firestore if found
        local_data = _load_local_store()
        users = local_data.get("users", {})
        for k, u in users.items():
            if isinstance(u, dict):
                if k == lower_ident or k == raw_ident or \
                   (u.get("email") and u.get("email").strip().lower() == lower_ident) or \
                   (u.get("mobile") and u.get("mobile").strip() == raw_ident) or \
                   (u.get("contact") and u.get("contact").strip().lower() == lower_ident):
                    enriched = _enrich(k, u)
                    try:
                        _firestore_client.collection("users").document(k).set(enriched, merge=True)
                    except Exception:
                        pass
                    return enriched

        return None
    else:
        data = _load_local_store()
        users = data.get("users", {})
        # 1. Direct key match
        if lower_ident in users:
            return _enrich(lower_ident, users[lower_ident])
        if raw_ident in users:
            return _enrich(raw_ident, users[raw_ident])
        # 2. Iterate and match email or mobile
        for k, u in users.items():
            if isinstance(u, dict):
                if u.get("email") and u.get("email").strip().lower() == lower_ident:
                    return _enrich(k, u)
                if u.get("mobile") and u.get("mobile").strip() == raw_ident:
                    return _enrich(k, u)
                if u.get("contact") and u.get("contact").strip().lower() == lower_ident:
                    return _enrich(k, u)
        return None


def verify_user_credentials(contact: str, plain_password: str) -> dict:
    """Verifies contact (email or mobile) and password against stored password hash. Returns user dict on success."""
    user = get_user_by_contact(contact)
    if not user:
        return None
    stored_hash = user.get("password_hash")
    if not stored_hash:
        # Check local store in case Firestore doc missed password_hash
        local_data = _load_local_store()
        for k, u in local_data.get("users", {}).items():
            if isinstance(u, dict):
                if k == str(contact).strip().lower() or u.get("email") == str(contact).strip().lower() or u.get("contact") == str(contact).strip().lower():
                    if u.get("password_hash"):
                        stored_hash = u["password_hash"]
                        # Auto-heal Firestore record
                        if _is_live_firestore and _firestore_client:
                            target_id = user.get("doc_id") or str(contact).strip().lower()
                            _firestore_client.collection("users").document(target_id).set({"password_hash": stored_hash}, merge=True)
                        break

    if stored_hash and verify_password(stored_hash, plain_password):
        # Update last login
        target_id = user.get("doc_id") or user.get("contact") or str(contact).strip().lower()
        update_user_profile(target_id, {"last_login": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        return user
    return None


def update_user_profile(contact: str, updates: dict) -> bool:
    """Updates user profile attributes in Firestore or local persistent store."""
    if not contact:
        return False
    clean_contact = str(contact).strip().lower()
    user = get_user_by_contact(contact)
    
    target_key = None
    if user:
        target_key = user.get("doc_id") or user.get("contact") or user.get("email")
    if not target_key:
        target_key = clean_contact

    target_key = str(target_key).strip().lower()

    # Ensure essential identifiers are preserved
    if "contact" not in updates:
        updates["contact"] = target_key
    if "email" not in updates and "@" in target_key:
        updates["email"] = target_key

    if _is_live_firestore and _firestore_client:
        doc_ref = _firestore_client.collection("users").document(target_key)
        doc_ref.set(updates, merge=True)

        # Keep local store in sync
        data = _load_local_store()
        if target_key in data.get("users", {}):
            data["users"][target_key].update(updates)
            _save_local_store(data)
        return True
    else:
        data = _load_local_store()
        updated = False
        if target_key in data.get("users", {}):
            data["users"][target_key].update(updates)
            updated = True
        if user:
            for k in [user.get("email"), user.get("mobile"), user.get("contact"), user.get("doc_id")]:
                if k and k in data.get("users", {}):
                    data["users"][k].update(updates)
                    updated = True
        if not updated:
            if "users" not in data:
                data["users"] = {}
            data["users"][target_key] = updates
            updated = True
        _save_local_store(data)
        return True


def update_user_password(contact: str, current_password: str, new_password: str) -> bool:
    """Verifies existing password and updates to new hashed password."""
    user = get_user_by_contact(contact)
    if not user:
        return False
    if not verify_password(user.get("password_hash"), current_password):
        return False

    return reset_user_password(contact, new_password)


def reset_user_password(contact: str, new_password: str) -> bool:
    """
    Directly updates the user password with a new hash without requiring current password.
    Used for verified OTP password reset workflows.
    """
    if not contact:
        return False
    user = get_user_by_contact(contact)
    target_key = None
    if user:
        target_key = user.get("doc_id") or user.get("contact") or user.get("email")
    if not target_key:
        target_key = str(contact).strip().lower()

    target_key = str(target_key).strip().lower()
    new_hash = hash_password(new_password)
    reset_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    payload = {
        "password_hash": new_hash,
        "password_reset_at": reset_timestamp
    }
    if user:
        if user.get("email"):
            payload["email"] = user.get("email")
        if user.get("name"):
            payload["name"] = user.get("name")
        if user.get("mobile"):
            payload["mobile"] = user.get("mobile")

    success = update_user_profile(target_key, payload)

    # Also update local store for all matching keys
    local_data = _load_local_store()
    local_users = local_data.get("users", {})
    all_keys = [target_key, str(contact).strip().lower()]
    if user:
        all_keys.extend([user.get("email"), user.get("mobile"), user.get("contact"), user.get("doc_id")])
    for k in set(filter(None, all_keys)):
        if k in local_users:
            local_users[k]["password_hash"] = new_hash
            local_users[k]["password_reset_at"] = reset_timestamp
    _save_local_store(local_data)

    return success



# -------------------------------------------------------------
# Certificate Generation History & Analytics
# -------------------------------------------------------------
def save_generation_record(contact: str, record_data: dict) -> str:
    """
    Saves a record of bulk certificate generation into Firestore.
    Includes project name, total certificates generated, template used, and timestamp.
    """
    contact = contact.strip().lower()
    record = {
        "contact": contact,
        "excel_name": record_data.get("excel_name", "students.xlsx"),
        "template_name": record_data.get("template_name", "template.jpg"),
        "total_certificates": int(record_data.get("total_certificates", 0)),
        "mappings_count": int(record_data.get("mappings_count", 0)),
        "pdf_filename": record_data.get("pdf_filename", "Generated_Certificates.pdf"),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    if _is_live_firestore and _firestore_client:
        doc_ref = _firestore_client.collection("generations").add(record)
        return doc_ref[1].id
    else:
        data = _load_local_store()
        record["id"] = f"gen_{len(data['generations']) + 1}"
        data["generations"].append(record)
        _save_local_store(data)
        return record["id"]


def get_user_generations(contact: str, limit: int = 10) -> list:
    """Fetches certificate generation history for a given user."""
    contact = contact.strip().lower()

    if _is_live_firestore and _firestore_client:
        try:
            from google.cloud.firestore import Query
            docs = (
                _firestore_client.collection("generations")
                .where("contact", "==", contact)
                .order_by("created_at", direction=Query.DESCENDING)
                .limit(limit)
                .stream()
            )
            records = [doc.to_dict() for doc in docs]
            return records
        except Exception:
            # Fallback query without compound index
            docs = _firestore_client.collection("generations").where("contact", "==", contact).stream()
            records = [doc.to_dict() for doc in docs]
            records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            return records[:limit]
    else:
        data = _load_local_store()
        user_records = [g for g in data["generations"] if g.get("contact") == contact]
        user_records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return user_records[:limit]


def get_user_stats(contact: str) -> dict:
    """Calculates user statistics: total batches run, total certificates generated."""
    contact = contact.strip().lower()
    generations = get_user_generations(contact, limit=100)

    total_batches = len(generations)
    total_certificates = sum(g.get("total_certificates", 0) for g in generations)

    return {
        "total_batches": total_batches,
        "total_certificates": total_certificates,
        "tier": "Pro",
        "status": "Active",
        "db_mode": "Google Cloud Firestore" if _is_live_firestore else "Local Persistent Database"
    }


def save_email_dispatch_record(contact: str, dispatch_data: dict) -> str:
    """Logs an email dispatch batch into Firebase Firestore."""
    contact = contact.strip().lower()
    record = {
        "contact": contact,
        "excel_name": dispatch_data.get("excel_name", "students.xlsx"),
        "subject": dispatch_data.get("subject", "Certificate Delivery"),
        "total_recipients": int(dispatch_data.get("total_recipients", 0)),
        "total_sent": int(dispatch_data.get("total_sent", 0)),
        "total_failed": int(dispatch_data.get("total_failed", 0)),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    if _is_live_firestore and _firestore_client:
        doc_ref = _firestore_client.collection("dispatches").add(record)
        return doc_ref[1].id
    else:
        data = _load_local_store()
        if "dispatches" not in data:
            data["dispatches"] = []
        record["id"] = f"disp_{len(data['dispatches']) + 1}"
        data["dispatches"].append(record)
        _save_local_store(data)
        return record["id"]


# -------------------------------------------------------------
# Certificate Designer Custom Templates & Saved Projects
# -------------------------------------------------------------
def save_user_design(contact: str, design_data: dict) -> str:
    """Saves a certificate design template created in the Canva-like Designer into Firebase."""
    import uuid
    contact = contact.strip().lower()
    design_id = design_data.get("id") or f"design_{uuid.uuid4().hex[:10]}"
    record = {
        "id": design_id,
        "contact": contact,
        "title": design_data.get("title", "Untitled Certificate"),
        "elements": design_data.get("elements", []),
        "background": design_data.get("background", {}),
        "canvas_size": design_data.get("canvas_size", {"width": 1050, "height": 742}),
        "thumbnail": design_data.get("thumbnail", ""),
        "preview_image": design_data.get("preview_image", ""),
        "aspect_ratio": design_data.get("aspect_ratio", "landscape-a4"),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    if _is_live_firestore and _firestore_client:
        _firestore_client.collection("designs").document(design_id).set(record)
    else:
        data = _load_local_store()
        if "designs" not in data:
            data["designs"] = {}
        data["designs"][design_id] = record
        _save_local_store(data)
    return design_id


def get_user_designs(contact: str) -> list:
    """Retrieves saved certificate designs for a user."""
    contact = contact.strip().lower()
    if _is_live_firestore and _firestore_client:
        try:
            docs = _firestore_client.collection("designs").where("contact", "==", contact).stream()
            designs = [d.to_dict() for d in docs]
            designs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
            return designs
        except Exception:
            return []
    else:
        data = _load_local_store()
        designs = [d for d in data.get("designs", {}).values() if d.get("contact") == contact]
        designs.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return designs


def delete_user_design(contact: str, design_id: str) -> bool:
    """Deletes a saved certificate design."""
    contact = contact.strip().lower()
    if _is_live_firestore and _firestore_client:
        doc_ref = _firestore_client.collection("designs").document(design_id)
        doc = doc_ref.get()
        if doc.exists and doc.to_dict().get("contact") == contact:
            doc_ref.delete()
            return True
        return False
    else:
        data = _load_local_store()
        if "designs" in data and design_id in data["designs"]:
            if data["designs"][design_id].get("contact") == contact:
                del data["designs"][design_id]
                _save_local_store(data)
                return True
        return False


# -------------------------------------------------------------
# User SMTP Email Settings (Per-User Isolated Accounts)
# -------------------------------------------------------------
def _resolve_user_smtp_key(contact: str) -> str:
    """Resolves the canonical database key for user's SMTP config."""
    if not contact:
        return ""
    clean = str(contact).strip().lower()
    user = get_user_by_contact(clean)
    if user:
        return (user.get("email") or user.get("doc_id") or clean).strip().lower()
    return clean


def save_user_smtp_config(contact: str, config_data: dict) -> bool:
    """
    Saves or updates a user's isolated SMTP configuration.
    Stores the encrypted App Password and metadata in Firestore or local store.
    """
    if not contact or not isinstance(config_data, dict):
        return False

    key = _resolve_user_smtp_key(contact)
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Load existing to preserve creation date if updating
    existing = get_user_smtp_config(contact, include_secret=True) or {}

    record = {
        "contact": key,
        "email": config_data.get("email", "").strip().lower(),
        "smtp_host": config_data.get("smtp_host", "smtp.gmail.com").strip(),
        "smtp_port": int(config_data.get("smtp_port", 587)),
        "security": config_data.get("security", "STARTTLS").strip().upper(),
        "sender_name": config_data.get("sender_name", "").strip(),
        "encrypted_app_password": config_data.get("encrypted_app_password") or existing.get("encrypted_app_password", ""),
        "is_verified": bool(config_data.get("is_verified", False)),
        "last_tested_at": config_data.get("last_tested_at") or existing.get("last_tested_at"),
        "created_at": existing.get("created_at", now_iso),
        "updated_at": now_iso
    }

    if _is_live_firestore and _firestore_client:
        _firestore_client.collection("smtp_configs").document(key).set(record, merge=True)
        # Mirror to local store
        data = _load_local_store()
        if "smtp_configs" not in data:
            data["smtp_configs"] = {}
        data["smtp_configs"][key] = record
        _save_local_store(data)
        return True
    else:
        data = _load_local_store()
        if "smtp_configs" not in data:
            data["smtp_configs"] = {}
        data["smtp_configs"][key] = record
        _save_local_store(data)
        return True


def get_user_smtp_config(contact: str, include_secret: bool = False) -> dict:
    """
    Fetches the user's isolated SMTP configuration.
    SECURITY GUARANTEE: If include_secret is False (the default for all API/view calls),
    the encrypted App Password is NEVER returned. Instead, 'has_password' (bool)
    and 'masked_password' are provided.
    """
    if not contact:
        return None

    key = _resolve_user_smtp_key(contact)
    raw_config = None

    if _is_live_firestore and _firestore_client:
        doc_ref = _firestore_client.collection("smtp_configs").document(key)
        doc = doc_ref.get()
        if doc.exists:
            raw_config = doc.to_dict()
        else:
            # Fallback to local store
            data = _load_local_store()
            raw_config = data.get("smtp_configs", {}).get(key)
    else:
        data = _load_local_store()
        raw_config = data.get("smtp_configs", {}).get(key)

    if not raw_config:
        return None

    has_pw = bool(raw_config.get("encrypted_app_password"))

    if include_secret:
        return dict(raw_config)

    # Return sanitized view safe for client / API responses
    safe_config = {
        "contact": key,
        "email": raw_config.get("email", ""),
        "smtp_host": raw_config.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": int(raw_config.get("smtp_port", 587)),
        "security": raw_config.get("security", "STARTTLS"),
        "sender_name": raw_config.get("sender_name", ""),
        "is_verified": bool(raw_config.get("is_verified", False)),
        "has_password": has_pw,
        "masked_password": "••••••••••••••••" if has_pw else "",
        "last_tested_at": raw_config.get("last_tested_at"),
        "created_at": raw_config.get("created_at"),
        "updated_at": raw_config.get("updated_at")
    }
    return safe_config


def delete_user_smtp_config(contact: str) -> bool:
    """
    Disconnects and permanently removes the user's SMTP configuration and encrypted credentials.
    """
    if not contact:
        return False
    key = _resolve_user_smtp_key(contact)

    if _is_live_firestore and _firestore_client:
        doc_ref = _firestore_client.collection("smtp_configs").document(key)
        doc_ref.delete()

    data = _load_local_store()
    if "smtp_configs" in data and key in data["smtp_configs"]:
        del data["smtp_configs"][key]
        _save_local_store(data)
        return True

    return True


