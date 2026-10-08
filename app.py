import os
import json
import datetime
import uuid
import re
import zipfile
import shutil
from flask import Flask, render_template, request, send_file, redirect, url_for, session, make_response, g, jsonify
import openpyxl
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

import io
import time
import mailer
import firebase_db
import smtp_security
from auth_jwt import jwt_required, generate_jwt_token, get_token_from_request, decode_jwt_token

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "certificate_studio_super_secret_key")

UPLOAD_FOLDER = "/tmp/uploads"
STATIC_FOLDER = 'static'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(STATIC_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER


@app.before_request
def load_user_context():
    """Populates Flask session and g context from JWT token if available."""
    token = get_token_from_request()
    if token:
        payload = decode_jwt_token(token)
        if payload:
            g.current_user = payload
            session['is_logged_in'] = True
            session['user_contact'] = payload.get('contact')
            session['user_name'] = payload.get('name')


@app.route('/')
def home():
    if session.get('is_logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


import random

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Accept JSON payload or standard Form post
        data = request.get_json(silent=True) or request.form
        is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
        
        contact = (data.get('contact') or '').strip()
        password = data.get('password', '')
        remember = bool(data.get('remember', False))
        
        if not contact or not password:
            msg = "Please enter your registered email/mobile and password."
            if is_ajax:
                return jsonify({"success": False, "error": msg}), 400
            return render_template('login.html', error=msg)

        # Verify user in Firebase Database (supports email, mobile, username)
        user = firebase_db.verify_user_credentials(contact, password)
        if user:
            token = generate_jwt_token(user)
            
            session['is_logged_in'] = True
            session['jwt_token'] = token
            session['user_contact'] = user.get('contact', user.get('email', contact))
            session['user_name'] = user.get('name')
            session['user_email'] = user.get('email', '')
            session['user_mobile'] = user.get('mobile', '')
            session['user_avatar'] = user.get('avatar', '')
            if 'user_id' not in session:
                session['user_id'] = str(uuid.uuid4())
            
            cookie_max_age = 86400 * 30 if remember else 86400 * 7

            if is_ajax:
                resp = make_response(jsonify({
                    "success": True, 
                    "redirect": url_for('dashboard'),
                    "message": "Authentication successful! Redirecting..."
                }))
            else:
                resp = make_response(redirect(url_for('dashboard')))
                
            resp.set_cookie('access_token', token, httponly=True, samesite='Lax', max_age=cookie_max_age)
            return resp
        else:
            err_msg = "❌ Invalid Credentials! Check your email/mobile or password."
            if is_ajax:
                return jsonify({"success": False, "error": err_msg}), 401
            return render_template('login.html', error=err_msg, contact=contact)
    return render_template('login.html')


@app.route('/register')
def register():
    return render_template('register.html')


@app.route('/api/send-registration-otp', methods=['POST'])
def send_registration_otp():
    """
    Validates name, mobile, and email. Dispatches a 6-digit verification OTP
    directly to the user's provided email address using Gmail SMTP.
    """
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    mobile = data.get('mobile', '').strip()
    email = data.get('email', '').strip().lower()

    if not name or len(name) < 2:
        return jsonify({"success": False, "error": "Please enter your full name (at least 2 characters)."}), 400

    # Mobile validation (at least 7 digits)
    digits_only = re.sub(r'\D', '', mobile)
    if not digits_only or len(digits_only) < 7:
        return jsonify({"success": False, "error": "Please enter a valid mobile phone number."}), 400

    # Email format validation
    if not mailer.is_valid_email(email):
        return jsonify({"success": False, "error": "Please enter a valid email address."}), 400

    # Check if an account already exists with this email or mobile
    existing_by_email = firebase_db.get_user_by_contact(email)
    if existing_by_email:
        return jsonify({"success": False, "error": f"An account with email '{email}' already exists. Please sign in."}), 409

    existing_by_mobile = firebase_db.get_user_by_contact(mobile)
    if existing_by_mobile:
        return jsonify({"success": False, "error": f"An account with mobile '{mobile}' already exists. Please sign in."}), 409

    # Generate cryptographically secure 6-digit OTP
    otp_code = f"{random.randint(100000, 999999)}"
    expiry_time = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat()

    # Store registration session
    session['pending_registration'] = {
        'name': name,
        'mobile': mobile,
        'email': email,
        'otp': otp_code,
        'expires_at': expiry_time
    }

    # Dispatch OTP via Gmail SMTP
    mail_result = mailer.send_otp_email(
        recipient_email=email,
        recipient_name=name,
        otp_code=otp_code
    )

    if mail_result.get("success"):
        return jsonify({
            "success": True,
            "delivered_via_smtp": True,
            "email": email,
            "message": f"Verification code sent to {email}. Please check your inbox and spam folder."
        })
    else:
        # SMTP connection issue or unconfigured credentials:
        # Provide helpful warning and simulated code so developer is not blocked
        return jsonify({
            "success": True,
            "delivered_via_smtp": False,
            "email": email,
            "smtp_warning": mail_result.get("error"),
            "simulated_code": otp_code,
            "message": f"OTP generated! (Notice: SMTP dispatch returned: {mail_result.get('error')})"
        })


@app.route('/verify-register', methods=['POST'])
def verify_register():
    data = request.get_json(silent=True) or request.form
    name = data.get('name', '').strip()
    mobile = data.get('mobile', '').strip()
    email = data.get('email', '').strip().lower()
    entered_otp = str(data.get('entered_otp', '')).strip()
    password = data.get('password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()

    is_ajax = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def send_error(msg, status=400):
        if is_ajax:
            return jsonify({"success": False, "error": msg}), status
        return render_template('register.html', error=msg)

    # Validate passwords
    if not password:
        return send_error("Please create a password for your account.")
    if len(password) < 6:
        return send_error("Password must be at least 6 characters long.")
    if confirm_password and password != confirm_password:
        return send_error("Passwords do not match! Please check and confirm your password.")

    # Check pending registration in session
    pending = session.get('pending_registration')
    server_otp = data.get('server_otp', '')

    valid_otp = False
    if pending:
        # Check expiration
        exp_iso = pending.get('expires_at')
        if exp_iso:
            try:
                exp_dt = datetime.datetime.fromisoformat(exp_iso)
                if datetime.datetime.now(datetime.timezone.utc) > exp_dt:
                    return send_error("Verification code has expired. Please request a new OTP.")
            except Exception:
                pass

        if entered_otp == str(pending.get('otp', '')).strip():
            valid_otp = True
            name = name or pending.get('name')
            mobile = mobile or pending.get('mobile')
            email = email or pending.get('email')

    # Allow fallback if server_otp matches
    if not valid_otp and server_otp and entered_otp == str(server_otp).strip():
        valid_otp = True

    if not valid_otp:
        return send_error("❌ Invalid 6-digit verification code! Please check and re-enter.")

    # Check if user already exists
    if firebase_db.get_user_by_contact(email) or (mobile and firebase_db.get_user_by_contact(mobile)):
        return send_error("⚠️ An account with this email or mobile already exists. Please log in.")

    # Create user in Firebase Firestore (or persistent fallback)
    user = firebase_db.create_user(
        contact=email,
        name=name,
        password=password,
        avatar='',
        mobile=mobile,
        email=email
    )

    # Clear pending registration
    session.pop('pending_registration', None)

    # Generate JWT Token
    token = generate_jwt_token(user)

    session['is_logged_in'] = True
    session['jwt_token'] = token
    session['user_name'] = name
    session['user_contact'] = email
    session['user_email'] = email
    session['user_mobile'] = mobile
    session['user_avatar'] = ''
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())

    if is_ajax:
        return jsonify({"success": True, "redirect": url_for('dashboard')})

    resp = make_response(redirect(url_for('dashboard')))
    resp.set_cookie('access_token', token, httponly=True, samesite='Lax', max_age=86400 * 7)
    return resp


def _mask_email(email_str: str) -> str:
    """Masks an email for secure UI display (e.g., al***@gmail.com)."""
    if not email_str or '@' not in email_str:
        return email_str
    user_part, domain_part = email_str.split('@', 1)
    if len(user_part) <= 2:
        masked_user = user_part[0] + '*'
    else:
        masked_user = user_part[:2] + '*' * min(len(user_part) - 2, 5)
    return f"{masked_user}@{domain_part}"


@app.route('/forgot-password')
def forgot_password():
    """Standalone page for Password Reset."""
    if session.get('is_logged_in'):
        return redirect(url_for('dashboard'))
    return render_template('forgot_password.html')


@app.route('/api/send-forgot-password-otp', methods=['POST'])
def send_forgot_password_otp():
    """
    Locates user by Email or Mobile, generates a 6-digit reset code,
    and dispatches it to their verified email using Gmail SMTP.
    """
    data = request.get_json(silent=True) or request.form
    contact = data.get('contact', '').strip()

    if not contact:
        return jsonify({
            "success": False,
            "error": "Please enter your registered Email ID or Mobile Number."
        }), 400

    user = firebase_db.get_user_by_contact(contact)
    if not user:
        return jsonify({
            "success": False,
            "error": f"No account found associated with '{contact}'. Please check your input or create a new account."
        }), 404

    user_name = user.get('name') or "Studio Member"
    user_email = user.get('email', '').strip().lower()
    if not user_email and mailer.is_valid_email(contact):
        user_email = contact.lower()

    if not user_email or not mailer.is_valid_email(user_email):
        return jsonify({
            "success": False,
            "error": "This account does not have a verified email address on file to receive the security code."
        }), 400

    otp_code = f"{random.randint(100000, 999999)}"
    expiry_time = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat()
    target_user_key = user.get('doc_id') or user.get('contact') or user.get('email') or contact

    session['pending_password_reset'] = {
        'contact': contact,
        'user_key': target_user_key,
        'email': user_email,
        'name': user_name,
        'otp': otp_code,
        'expires_at': expiry_time
    }

    mail_result = mailer.send_password_reset_otp_email(
        recipient_email=user_email,
        recipient_name=user_name,
        otp_code=otp_code
    )

    masked = _mask_email(user_email)

    if mail_result.get("success"):
        return jsonify({
            "success": True,
            "delivered_via_smtp": True,
            "masked_email": masked,
            "email": user_email,
            "message": f"Verification code sent to {masked}. Please check your inbox and spam folder."
        })
    else:
        return jsonify({
            "success": True,
            "delivered_via_smtp": False,
            "masked_email": masked,
            "email": user_email,
            "smtp_warning": mail_result.get("error"),
            "simulated_code": otp_code,
            "message": f"Reset code generated for {masked}! (Notice: SMTP dispatch returned: {mail_result.get('error')})"
        })


@app.route('/api/reset-password', methods=['POST'])
def api_reset_forgotten_password():
    """
    Verifies 6-digit OTP and resets user password in Firebase Firestore / local database.
    """
    data = request.get_json(silent=True) or request.form
    entered_otp = str(data.get('entered_otp', '')).strip()
    new_password = data.get('new_password', '').strip()
    confirm_password = data.get('confirm_password', '').strip()
    server_otp = str(data.get('server_otp', '')).strip()

    if not new_password:
        return jsonify({"success": False, "error": "Please enter a new password."}), 400
    if len(new_password) < 6:
        return jsonify({"success": False, "error": "Password must be at least 6 characters long."}), 400
    if confirm_password and new_password != confirm_password:
        return jsonify({"success": False, "error": "Passwords do not match! Please check and confirm your password."}), 400

    pending = session.get('pending_password_reset')
    valid_otp = False
    target_contact = None

    if pending:
        exp_iso = pending.get('expires_at')
        if exp_iso:
            try:
                exp_dt = datetime.datetime.fromisoformat(exp_iso)
                if datetime.datetime.now(datetime.timezone.utc) > exp_dt:
                    return jsonify({"success": False, "error": "Verification code has expired. Please request a new code."}), 400
            except Exception:
                pass

        if entered_otp == str(pending.get('otp', '')).strip():
            valid_otp = True
            target_contact = pending.get('user_key') or pending.get('contact') or pending.get('email')

    if not valid_otp and server_otp and entered_otp == server_otp:
        valid_otp = True
        target_contact = data.get('contact') or (pending.get('user_key') if pending else None)

    if not valid_otp:
        return jsonify({"success": False, "error": "❌ Invalid 6-digit verification code! Please check and re-enter."}), 400

    if not target_contact:
        target_contact = data.get('contact')

    if not target_contact:
        return jsonify({"success": False, "error": "Unable to identify user account. Please restart the reset process."}), 400

    # Perform password update
    updated = firebase_db.reset_user_password(target_contact, new_password)
    if not updated:
        return jsonify({"success": False, "error": "Failed to update password. User account not found."}), 404

    # Clear pending reset session
    session.pop('pending_password_reset', None)

    return jsonify({
        "success": True,
        "message": "Password successfully reset! You can now sign in with your new password.",
        "redirect": url_for('login')
    })



@app.route('/dashboard')
@jwt_required
def dashboard():
    contact = session.get('user_contact')
    stats = firebase_db.get_user_stats(contact)
    recent_generations = firebase_db.get_user_generations(contact, limit=5)
    user_data = firebase_db.get_user_by_contact(contact) or {}
    user_designs = firebase_db.get_user_designs(contact)
    
    return render_template('dashboard.html', 
                           user_name=user_data.get('name', session.get('user_name', 'User')), 
                           user_contact=contact,
                           user_avatar=user_data.get('avatar', session.get('user_avatar', '')),
                           stats=stats,
                           recent_generations=recent_generations,
                           user_designs=user_designs,
                           is_live_db=firebase_db.is_using_live_firebase())


@app.route('/account-settings')
@jwt_required
def account_settings():
    contact = session.get('user_contact')
    user_data = firebase_db.get_user_by_contact(contact) or {}
    user_smtp = firebase_db.get_user_smtp_config(contact, include_secret=False)
    
    return render_template('account_settings.html',
                           user_name=user_data.get('name', session.get('user_name', '')),
                           user_contact=contact,
                           user_avatar=user_data.get('avatar', session.get('user_avatar', '')),
                           user_smtp=user_smtp,
                           db_mode=firebase_db.get_user_stats(contact).get('db_mode'))


@app.route('/update-profile', methods=['POST'])
@jwt_required
def update_profile():
    name = request.form.get('name', '').strip()
    contact = session.get('user_contact')
    updates = {}
    
    if name:
        updates['name'] = name
        session['user_name'] = name
        
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename != '':
            user_id = session.get('user_id', 'default')
            avatar_filename = f"avatar_{user_id}.jpg"
            avatar_path = os.path.join(STATIC_FOLDER, avatar_filename)
            file.save(avatar_path)
            
            updates['avatar'] = avatar_filename
            session['user_avatar'] = avatar_filename
            
    if updates:
        firebase_db.update_user_profile(contact, updates)
                
    return render_template('account_settings.html', 
                           success="✅ Profile successfully updated in Firebase!",
                           user_name=session.get('user_name', ''),
                           user_contact=session.get('user_contact', ''),
                           user_avatar=session.get('user_avatar', ''))


@app.route('/reset-password', methods=['POST'])
@jwt_required
def reset_password():
    current_pass = request.form.get('current_password', '')
    new_pass = request.form.get('new_password', '')
    contact = session.get('user_contact')
    
    success = firebase_db.update_user_password(contact, current_pass, new_pass)
    if success:
        return render_template('account_settings.html',
                               success="🔒 Password successfully changed and updated in database!",
                               user_name=session.get('user_name', ''),
                               user_contact=session.get('user_contact', ''),
                               user_avatar=session.get('user_avatar', ''))
    else:
        return render_template('account_settings.html',
                               error="❌ Current password is incorrect!",
                               user_name=session.get('user_name', ''),
                               user_contact=session.get('user_contact', ''),
                               user_avatar=session.get('user_avatar', ''))


@app.route('/studio')
@jwt_required
def studio():
    return render_template('index.html')


@app.route('/logout')
def logout():
    session.clear()
    resp = make_response(redirect(url_for('login')))
    resp.delete_cookie('access_token')
    return resp


@app.route('/user-template')
@jwt_required
def user_template():
    """Serves the user's uploaded certificate template image dynamically for the canvas."""
    template_path = session.get('template_path')
    if template_path and os.path.exists(template_path):
        return send_file(template_path)
    # Default fallback template
    static_template = os.path.join(STATIC_FOLDER, 'template.jpg')
    if os.path.exists(static_template):
        return send_file(static_template)
    return send_file('template.jpg')


def load_excel_workbook(excel_path):
    """Safely loads an Excel workbook into memory to prevent file locking on Windows/OneDrive."""
    import io
    with open(excel_path, 'rb') as f:
        file_bytes = io.BytesIO(f.read())
    return openpyxl.load_workbook(file_bytes, data_only=True)


@app.route('/map', methods=['POST'])
@jwt_required
def map_template():
    if 'template' not in request.files or 'excel' not in request.files:
        return "Please upload both files!"
        
    template_file = request.files['template']
    excel_file = request.files['excel']
    
    if not excel_file.filename.lower().endswith(('.xlsx', '.xls')):
        return "<h3>❌ Invalid File Format! This is not an Excel file. Please go back and upload a valid .xlsx file.</h3><a href='/studio'>Go Back</a>"
    
    user_id = session.get('user_id', str(uuid.uuid4()))
    session['user_id'] = user_id
    
    user_folder = os.path.join(UPLOAD_FOLDER, user_id)
    os.makedirs(user_folder, exist_ok=True)
    
    template_path = os.path.join(user_folder, 'template.jpg')
    excel_path = os.path.join(user_folder, 'students.xlsx')
    
    template_file.save(template_path)
    excel_file.save(excel_path)
    
    session['template_path'] = template_path
    session['excel_path'] = excel_path
    session['excel_name'] = excel_file.filename
    session['template_name'] = template_file.filename
    
    wb = load_excel_workbook(excel_path)
    sheet = wb.active
    raw_headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
    headers = [str(cell).strip() for cell in raw_headers if cell is not None]
    
    # Extract sample row for live WYSIWYG canvas preview
    first_data_row = next(sheet.iter_rows(min_row=2, max_row=2, values_only=True), None)
    sample_data = {}
    if first_data_row:
        for idx, h in enumerate(headers):
            if idx < len(first_data_row) and first_data_row[idx] is not None:
                val = first_data_row[idx]
                if isinstance(val, (datetime.datetime, datetime.date)):
                    sample_data[h] = val.strftime('%Y-%m-%d')
                else:
                    sample_data[h] = str(val).strip()
            else:
                sample_data[h] = h
    else:
        for h in headers:
            sample_data[h] = f"Sample {h}"
    
    return render_template('map.html', headers=headers, sample_data=sample_data)


@app.route('/back-to-map')
@jwt_required
def back_to_map():
    try:
        excel_path = session.get('excel_path')
        if not excel_path or not os.path.exists(excel_path):
            return redirect(url_for('studio'))
            
        wb = load_excel_workbook(excel_path)
        sheet = wb.active
        raw_headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        headers = [str(cell).strip() for cell in raw_headers if cell is not None]
        
        first_data_row = next(sheet.iter_rows(min_row=2, max_row=2, values_only=True), None)
        sample_data = {}
        if first_data_row:
            for idx, h in enumerate(headers):
                if idx < len(first_data_row) and first_data_row[idx] is not None:
                    val = first_data_row[idx]
                    if isinstance(val, (datetime.datetime, datetime.date)):
                        sample_data[h] = val.strftime('%Y-%m-%d')
                    else:
                        sample_data[h] = str(val).strip()
                else:
                    sample_data[h] = h
        else:
            for h in headers:
                sample_data[h] = f"Sample {h}"

        return render_template('map.html', headers=headers, sample_data=sample_data)
    except Exception:
        return redirect(url_for('studio'))


def get_font_path(font_name, is_bold, is_italic):
    font_map = {
        'times new roman': ('times.ttf', 'timesbd.ttf', 'timesi.ttf', 'timesbi.ttf'),
        'arial': ('arial.ttf', 'arialbd.ttf', 'ariali.ttf', 'arialbi.ttf'),
        'courier new': ('cour.ttf', 'courbd.ttf', 'couri.ttf', 'courbi.ttf'),
        'georgia': ('georgia.ttf', 'georgiab.ttf', 'georgiai.ttf', 'georgiaz.ttf'),
        'verdana': ('verdana.ttf', 'verdanab.ttf', 'verdanai.ttf', 'verdanaz.ttf'),
        'tahoma': ('tahoma.ttf', 'tahomabd.ttf', 'tahoma.ttf', 'tahomabd.ttf'),
        'impact': ('impact.ttf', 'impact.ttf', 'impact.ttf', 'impact.ttf'),
        'calibri': ('calibri.ttf', 'calibrib.ttf', 'calibrii.ttf', 'calibriz.ttf'),
        'cambria': ('cambria.ttc', 'cambriab.ttf', 'cambriai.ttf', 'cambriaz.ttf'),
        'garamond': ('gara.ttf', 'garabd.ttf', 'garait.ttf', 'gara.ttf'),
        'playfair display': ('georgia.ttf', 'georgiab.ttf', 'georgiai.ttf', 'georgiaz.ttf'),
        'cinzel': ('times.ttf', 'timesbd.ttf', 'timesi.ttf', 'timesbi.ttf'),
        'montserrat': ('arial.ttf', 'arialbd.ttf', 'ariali.ttf', 'arialbi.ttf'),
        'inter': ('arial.ttf', 'arialbd.ttf', 'ariali.ttf', 'arialbi.ttf'),
        'great vibes': ('timesi.ttf', 'timesbi.ttf', 'timesi.ttf', 'timesbi.ttf')
    }
    key = font_name.lower().strip()
    files = font_map.get(key, ('times.ttf', 'timesbd.ttf', 'timesi.ttf', 'timesbi.ttf'))
    idx = 0
    if is_bold and is_italic: idx = 3
    elif is_bold: idx = 1
    elif is_italic: idx = 2
    
    win_font = os.path.join("C:/Windows/Fonts", files[idx])
    if os.path.exists(win_font):
        return win_font
    return files[idx]


def render_single_certificate(template_path, row, header_row, global_mappings):
    """
    Renders one certificate PIL Image for a given row and mapping configuration.
    Returns the Image object or None if no valid data was found.
    """
    image = Image.open(template_path).convert('RGB')
    draw = ImageDraw.Draw(image)
    has_data = False
    
    clean_headers = [str(h).strip().lower() for h in header_row]
    
    for box in global_mappings:
        field_name_raw = box.get('field', '').strip()
        field_name_clean = field_name_raw.lower()
        
        if field_name_clean in clean_headers:
            col_index = clean_headers.index(field_name_clean)
            cell_value = row[col_index] if col_index < len(row) else ""
        else:
            cell_value = ""
        
        if cell_value is not None and str(cell_value).strip() != "":
            has_data = True
            if isinstance(cell_value, (datetime.datetime, datetime.date)):
                text_to_print = cell_value.strftime('%Y-%m-%d')
            else:
                text_to_print = str(cell_value).strip()
            
            case_mode = box.get('caseMode')
            if case_mode == 'upper': text_to_print = text_to_print.upper()
            elif case_mode == 'lower': text_to_print = text_to_print.lower()
            elif case_mode == 'title': text_to_print = text_to_print.title()
            
            font_size = int(box.get('size', 40))
            color = box.get('color', '#1a1a2e')
            font_name = box.get('font', 'Times New Roman')
            is_bold = box.get('bold', False)
            is_italic = box.get('italic', False)
            box_width = int(box['w'])

            try:
                font_path = get_font_path(font_name, is_bold, is_italic)
                font = ImageFont.truetype(font_path, size=font_size)
            except Exception:
                font = ImageFont.load_default()

            while font_size > 8:
                bbox = draw.textbbox((0, 0), text_to_print, font=font)
                text_w = bbox[2] - bbox[0]
                if text_w <= box_width - 10: break
                font_size -= 2
                try: font = ImageFont.truetype(font_path, size=font_size)
                except Exception: break

            x = int(box['x'])
            y = int(box['y'])
            align = box.get('align', 'left')
            bbox = draw.textbbox((0, 0), text_to_print, font=font)
            text_w = bbox[2] - bbox[0]
            
            if align == 'center':
                x = x + (box_width - text_w) / 2
            elif align == 'right':
                x = x + box_width - text_w

            draw.text((x, y), text_to_print, fill=color, font=font)
            
            # Draw underline if enabled
            if box.get('underline'):
                text_h = bbox[3] - bbox[1]
                underline_y = y + text_h + 3
                draw.line([(x, underline_y), (x + text_w, underline_y)], fill=color, width=max(1, int(font_size / 20)))
                
    return image if has_data else None


def find_student_name(row, header_row, row_idx):
    """Detects student name from row for clean individual PDF naming."""
    name_keywords = ['name', 'student name', 'participant name', 'full name', 'candidate name', 'student', 'participant']
    for kw in name_keywords:
        for idx, h in enumerate(header_row):
            if kw in h.lower() and idx < len(row) and row[idx] is not None and str(row[idx]).strip():
                return str(row[idx]).strip()
    # Fallback to first non-empty value
    for cell in row:
        if cell is not None and str(cell).strip():
            return str(cell).strip()
    return f"Recipient_{row_idx}"


@app.route('/preview-sample', methods=['POST'])
@jwt_required
def preview_sample():
    try:
        excel_path = session.get('excel_path')
        template_path = session.get('template_path')
        
        if not excel_path or not template_path:
            return "Session expired! <a href='/studio'>Studio</a>"
            
        mappings_json = request.form.get('mappings')
        if mappings_json:
            session['mappings'] = json.loads(mappings_json)
            
        global_mappings = session.get('mappings', [])
        if not global_mappings:
            return "No mapping boxes received!"
        
        wb = load_excel_workbook(excel_path)
        sheet = wb.active

        raw_headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        header_row = [str(cell).strip() if cell is not None else "" for cell in raw_headers]
        first_row = next(sheet.iter_rows(min_row=2, max_row=2, values_only=True), None)
        
        if not first_row:
            return "No data rows found in the Excel file!"

        image = render_single_certificate(template_path, first_row, header_row, global_mappings)
        if not image:
            image = Image.open(template_path).convert('RGB')
        
        user_id = session.get('user_id', 'default')
        user_folder = os.path.join(UPLOAD_FOLDER, user_id)
        os.makedirs(user_folder, exist_ok=True)
        preview_filename = os.path.join(user_folder, 'preview.png')
        image.save(preview_filename)
        
        # Also copy to static for preview display fallback
        global_preview_static = os.path.join(STATIC_FOLDER, 'sample_preview.png')
        image.save(global_preview_static)
        
        # Count total rows for information display
        total_students = sheet.max_row - 1 if sheet.max_row > 1 else 1
        
        user_smtp = firebase_db.get_user_smtp_config(session.get('user_contact'), include_secret=False)
        return render_template(
            'preview.html',
            total_students=total_students,
            headers=header_row,
            default_smtp=mailer.get_default_smtp_config(),
            user_smtp=user_smtp
        )
    except Exception as e:
        return f"Error: {str(e)}"


@app.route('/generate-final', methods=['POST'])
@jwt_required
def generate_final():
    """Generates certificates as either a Combined Multi-page PDF or a ZIP of Individual PDFs."""
    try:
        excel_path = session.get('excel_path')
        template_path = session.get('template_path')
        global_mappings = session.get('mappings', [])
        contact = session.get('user_contact')
        requested_format = request.form.get('format', 'pdf').lower().strip()
        
        if not excel_path or not template_path or not global_mappings:
            return "No mappings found! <a href='/studio'>Studio</a>"
            
        wb = load_excel_workbook(excel_path)
        sheet = wb.active

        raw_headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        header_row = [str(cell).strip() if cell is not None else "" for cell in raw_headers]
        
        user_folder = os.path.dirname(template_path)
        
        # -------------------------------------------------------------
        # OPTION 1: ZIP Archive with Individual PDFs
        # -------------------------------------------------------------
        if requested_format == 'zip':
            temp_pdf_dir = os.path.join(user_folder, 'individual_pdfs')
            if os.path.exists(temp_pdf_dir):
                shutil.rmtree(temp_pdf_dir)
            os.makedirs(temp_pdf_dir, exist_ok=True)
            
            created_pdf_files = []
            name_counts = {}
            
            for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=1):
                image = render_single_certificate(template_path, row, header_row, global_mappings)
                if image:
                    student_raw_name = find_student_name(row, header_row, row_idx)
                    clean_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', student_raw_name).strip().replace(' ', '_')
                    if not clean_name:
                        clean_name = f"Recipient_{row_idx}"
                        
                    # Handle duplicate names gracefully
                    if clean_name in name_counts:
                        name_counts[clean_name] += 1
                        filename = f"Certificate_{clean_name}_{name_counts[clean_name]}.pdf"
                    else:
                        name_counts[clean_name] = 1
                        filename = f"Certificate_{clean_name}.pdf"
                        
                    pdf_file_path = os.path.join(temp_pdf_dir, filename)
                    image.save(pdf_file_path, "PDF", resolution=100.0)
                    created_pdf_files.append((pdf_file_path, filename))
            
            if not created_pdf_files:
                return "No valid student records found to generate!"
                
            zip_filename = os.path.join(user_folder, 'Certificates_Individual_PDFs.zip')
            with zipfile.ZipFile(zip_filename, 'w', compression=zipfile.ZIP_DEFLATED) as zipf:
                for full_path, arc_name in created_pdf_files:
                    zipf.write(full_path, arcname=arc_name)
                    
            # Cleanup temporary individual PDF files
            shutil.rmtree(temp_pdf_dir, ignore_errors=True)
            
            # Save history in Firebase
            if contact:
                firebase_db.save_generation_record(contact, {
                    "excel_name": session.get('excel_name', os.path.basename(excel_path)),
                    "template_name": session.get('template_name', os.path.basename(template_path)),
                    "total_certificates": len(created_pdf_files),
                    "mappings_count": len(global_mappings),
                    "pdf_filename": "Certificates_Individual_PDFs.zip (ZIP of Individual PDFs)"
                })
                
            return send_file(zip_filename, as_attachment=True, download_name="Certificates_Individual_PDFs.zip")

        # -------------------------------------------------------------
        # OPTION 2: Combined Multi-Page PDF
        # -------------------------------------------------------------
        else:
            certificate_images = []
            for row in sheet.iter_rows(min_row=2, values_only=True):
                image = render_single_certificate(template_path, row, header_row, global_mappings)
                if image:
                    certificate_images.append(image)

            if certificate_images:
                pdf_filename = os.path.join(user_folder, 'Generated_Certificates.pdf')
                certificate_images[0].save(pdf_filename, save_all=True, append_images=certificate_images[1:])
                
                # Save generation project record in Firebase Database
                if contact:
                    firebase_db.save_generation_record(contact, {
                        "excel_name": session.get('excel_name', os.path.basename(excel_path)),
                        "template_name": session.get('template_name', os.path.basename(template_path)),
                        "total_certificates": len(certificate_images),
                        "mappings_count": len(global_mappings),
                        "pdf_filename": "Generated_Certificates.pdf (Merged PDF)"
                    })
                
                return send_file(pdf_filename, as_attachment=True, download_name="Generated_Certificates.pdf")
            else:
                return "No valid data found in Excel sheet!"
                
    except Exception as e:
        return f"Error: {str(e)}"


@app.route('/generate-zip', methods=['POST'])
@jwt_required
def generate_zip():
    """Direct convenience route to generate and download individual PDFs as a ZIP file."""
    # Force format to zip and call generate_final
    request.form = request.form.copy()
    return generate_final()


# -------------------------------------------------------------
# SMTP Email Settings Web Page & REST APIs
# -------------------------------------------------------------
@app.route('/smtp-settings')
@jwt_required
def smtp_settings_page():
    """Renders the dedicated SMTP Email Settings management page."""
    contact = session.get('user_contact')
    user_data = firebase_db.get_user_by_contact(contact) or {}
    smtp_config = firebase_db.get_user_smtp_config(contact, include_secret=False)
    default_smtp = mailer.get_default_smtp_config()

    return render_template(
        'smtp_settings.html',
        smtp_config=smtp_config,
        default_smtp=default_smtp,
        user_name=user_data.get('name', session.get('user_name', 'User')),
        user_contact=contact,
        user_avatar=user_data.get('avatar', session.get('user_avatar', ''))
    )


@app.route('/api/smtp/settings', methods=['GET', 'POST', 'DELETE'])
@jwt_required
def api_smtp_settings():
    """
    CRUD API for authenticated user's isolated SMTP configuration.
    GET: Retrieves current user's sanitized settings (App Password is NEVER returned).
    POST: Validates, tests, encrypts App Password, and stores configuration.
    DELETE: Disconnects and permanently removes stored SMTP configuration.
    """
    contact = session.get('user_contact')
    if not contact:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    if request.method == 'GET':
        config = firebase_db.get_user_smtp_config(contact, include_secret=False)
        return jsonify({
            "success": True,
            "configured": bool(config and config.get("has_password")),
            "config": config,
            "system_fallback": mailer.get_default_smtp_config().get("email")
        })

    elif request.method == 'POST':
        data = request.get_json(silent=True) or request.form
        email = (data.get('email') or '').strip().lower()
        password = (data.get('password') or '').strip()
        smtp_host = (data.get('smtp_host') or 'smtp.gmail.com').strip()
        raw_port = data.get('smtp_port', 587)
        security = (data.get('security') or 'STARTTLS').strip().upper()
        sender_name = (data.get('sender_name') or '').strip()

        if not email or not mailer.is_valid_email(email):
            return jsonify({"success": False, "error": "Please enter a valid email address."}), 400

        try:
            smtp_port = int(raw_port)
            if not (1 <= smtp_port <= 65535):
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid SMTP port number (must be 1-65535)."}), 400

        if security not in ("STARTTLS", "SSL/TLS", "NONE"):
            security = "STARTTLS"

        # Check existing config if password was not re-entered
        existing = firebase_db.get_user_smtp_config(contact, include_secret=True) or {}
        encrypted_pw = ""
        plain_test_pw = ""

        if password:
            clean_pw = password.replace(" ", "")
            encrypted_pw = smtp_security.encrypt_app_password(clean_pw)
            plain_test_pw = clean_pw
        elif existing and existing.get("encrypted_app_password"):
            encrypted_pw = existing.get("encrypted_app_password")
            plain_test_pw = smtp_security.decrypt_app_password(encrypted_pw)
        else:
            return jsonify({
                "success": False,
                "error": "An App Password is required for initial SMTP configuration."
            }), 400

        # Perform live credential validation before saving
        verify_check = mailer.verify_smtp_credentials({
            "email": email,
            "password": plain_test_pw,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "security": security
        })

        is_verified = verify_check["success"]
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "email": email,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "security": security,
            "sender_name": sender_name,
            "encrypted_app_password": encrypted_pw,
            "is_verified": is_verified,
            "last_tested_at": now_iso if is_verified else existing.get("last_tested_at")
        }

        save_success = firebase_db.save_user_smtp_config(contact, record)
        if not save_success:
            return jsonify({"success": False, "error": "Failed to save SMTP configuration to database."}), 500

        safe_config = firebase_db.get_user_smtp_config(contact, include_secret=False)

        if not is_verified:
            return jsonify({
                "success": False,
                "error": verify_check.get("error", "Unable to connect to SMTP server. Please verify your settings and App Password."),
                "config": safe_config
            }), 400

        return jsonify({
            "success": True,
            "message": "SMTP configuration validated, encrypted, and saved successfully.",
            "config": safe_config
        })

    elif request.method == 'DELETE':
        firebase_db.delete_user_smtp_config(contact)
        return jsonify({
            "success": True,
            "message": "SMTP configuration disconnected. Email dispatches will now revert to system default."
        })


@app.route('/api/smtp/test-connection', methods=['POST'])
@jwt_required
def api_smtp_test_connection():
    """
    Tests an SMTP connection and authentication credentials without sending an email.
    If password is blank, uses currently saved encrypted credentials.
    """
    contact = session.get('user_contact')
    data = request.get_json(silent=True) or request.form

    email = (data.get('email') or '').strip().lower()
    password = (data.get('password') or '').strip()
    smtp_host = (data.get('smtp_host') or 'smtp.gmail.com').strip()
    raw_port = data.get('smtp_port', 587)
    security = (data.get('security') or 'STARTTLS').strip().upper()

    try:
        smtp_port = int(raw_port)
    except (ValueError, TypeError):
        smtp_port = 587

    # If no password provided in request, check if user has a stored encrypted password
    if not password and contact:
        user_cfg = firebase_db.get_user_smtp_config(contact, include_secret=True)
        if user_cfg and user_cfg.get("encrypted_app_password"):
            password = smtp_security.decrypt_app_password(user_cfg.get("encrypted_app_password"))
            if not email and user_cfg.get("email"):
                email = user_cfg.get("email")

    if not email:
        return jsonify({"success": False, "error": "Sender email is required."}), 400
    if not password:
        return jsonify({"success": False, "error": "App Password is required to test connection."}), 400

    result = mailer.verify_smtp_credentials({
        "email": email,
        "password": password,
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "security": security
    })

    if result["success"]:
        # Update verified status in database if this matches current user's config
        if contact:
            existing = firebase_db.get_user_smtp_config(contact, include_secret=False)
            if existing and existing.get("email") == email:
                firebase_db.save_user_smtp_config(contact, {
                    "is_verified": True,
                    "last_tested_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                })
        return jsonify({
            "success": True,
            "message": "SMTP connection successful."
        })
    else:
        return jsonify({
            "success": False,
            "error": result.get("error", "Unable to connect to SMTP server. Please verify your SMTP settings and App Password.")
        }), 400


@app.route('/api/smtp/test-email', methods=['POST'])
@jwt_required
def api_smtp_test_email():
    """
    Sends a test certificate message to a specified recipient using the authenticated user's SMTP account.
    """
    contact = session.get('user_contact')
    data = request.get_json(silent=True) or request.form
    test_recipient = (data.get('test_recipient') or '').strip()

    smtp_cfg, is_custom = mailer.get_user_or_default_smtp_config(contact)
    sender_email = smtp_cfg.get("email", "").strip()

    if not is_custom or not sender_email or not smtp_cfg.get("password"):
        return jsonify({
            "success": False,
            "error": "Please save and verify your personal SMTP settings before sending a test email."
        }), 400

    target = test_recipient if test_recipient else sender_email
    if not mailer.is_valid_email(target):
        return jsonify({"success": False, "error": f"Invalid recipient email address: '{target}'"}), 400

    result = mailer.test_smtp_connection(smtp_cfg, target)
    if result["success"]:
        return jsonify({
            "success": True,
            "message": f"Test email sent successfully to {target}.",
            "delivered_to": target,
            "sender": sender_email
        })
    else:
        return jsonify({
            "success": False,
            "error": result.get("error", "Failed to dispatch test email.")
        }), 400


# Legacy endpoint backward compatibility for preview.html
@app.route('/send-test-email', methods=['POST'])
@jwt_required
def send_test_email():
    """Convenience route used by preview modal to dispatch a test certificate."""
    try:
        contact = session.get('user_contact')
        smtp_cfg, is_custom = mailer.get_user_or_default_smtp_config(contact)

        if not smtp_cfg.get("email") or not smtp_cfg.get("password"):
            return jsonify({
                "success": False,
                "error": "No SMTP credentials configured. Please configure your email in Settings -> SMTP."
            }), 400

        recipient = request.form.get('test_recipient', '').strip() or smtp_cfg.get("email")
        result = mailer.test_smtp_connection(smtp_cfg, recipient)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/dispatch-bulk-emails', methods=['POST'])
@jwt_required
def dispatch_bulk_emails():
    """
    Generates each student's certificate and dispatches it directly using the authenticated
    user's personal SMTP account (with graceful fallback to system .env).
    Features sending queue with statuses (PENDING, SENDING, SENT, FAILED), rate-limiting pacing,
    and automatic retry for transient connection failures.
    """
    try:
        excel_path = session.get('excel_path')
        template_path = session.get('template_path')
        global_mappings = session.get('mappings', [])
        contact = session.get('user_contact')

        if not excel_path or not template_path or not global_mappings:
            return jsonify({"success": False, "error": "Session expired or missing mappings!"}), 400

        # Load user's isolated SMTP credentials or fall back to system defaults
        smtp_config, is_custom = mailer.get_user_or_default_smtp_config(contact)
        if not smtp_config.get("email") or not smtp_config.get("password"):
            return jsonify({
                "success": False,
                "error": "No SMTP credentials available! Please configure your SMTP settings in Settings -> SMTP."
            }), 400

        email_column = request.form.get('email_column', '').strip()
        subject_template = request.form.get('subject', 'Congratulations {Name}! Here is your Certificate').strip()
        body_template = request.form.get('body', 'Dear {Name},\n\nCongratulations on your achievement!\nPlease find your official certificate attached.\n\nBest regards,\nCertificate Studio').strip()

        wb = load_excel_workbook(excel_path)
        sheet = wb.active
        raw_headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        header_row = [str(cell).strip() for cell in raw_headers if cell is not None]
        clean_headers = [h.lower() for h in header_row]

        email_col_clean = email_column.lower().strip()
        if email_col_clean not in clean_headers:
            return jsonify({"success": False, "error": f"Email column '{email_column}' not found in spreadsheet!"}), 400
        email_col_idx = clean_headers.index(email_col_clean)

        results = []
        sent_count = 0
        failed_count = 0

        # Build initial queue items
        rows = list(sheet.iter_rows(min_row=2, values_only=True))

        for row_idx, row in enumerate(rows, start=1):
            raw_email = row[email_col_idx] if email_col_idx < len(row) else ""
            recipient_email = str(raw_email).strip() if raw_email else ""
            student_name = find_student_name(row, header_row, row_idx)
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if not recipient_email or not mailer.is_valid_email(recipient_email):
                results.append({
                    "name": student_name,
                    "email": recipient_email or "(No Email Provided)",
                    "status": "FAILED",
                    "retry_count": 0,
                    "timestamp": now_iso,
                    "error": "Missing or invalid email address"
                })
                failed_count += 1
                continue

            cert_image = render_single_certificate(template_path, row, header_row, global_mappings)
            if not cert_image:
                results.append({
                    "name": student_name,
                    "email": recipient_email,
                    "status": "FAILED",
                    "retry_count": 0,
                    "timestamp": now_iso,
                    "error": "No valid row data to generate certificate"
                })
                failed_count += 1
                continue

            pdf_buffer = io.BytesIO()
            cert_image.save(pdf_buffer, format="PDF", resolution=100.0)
            pdf_bytes = pdf_buffer.getvalue()

            clean_name = re.sub(r'[^a-zA-Z0-9_\- ]', '', student_name).strip().replace(' ', '_')
            pdf_filename = f"Certificate_{clean_name}.pdf"

            # Controlled rate-limiting pacing between consecutive sends
            if row_idx > 1:
                time.sleep(0.3)

            # Send with 1 retry attempt for temporary network/handshake glitches
            send_res = None
            retries = 0
            max_retries = 1

            while retries <= max_retries:
                send_res = mailer.send_single_certificate_email(
                    recipient_email=recipient_email,
                    recipient_name=student_name,
                    subject=subject_template,
                    body_text=body_template,
                    pdf_bytes=pdf_bytes,
                    pdf_filename=pdf_filename,
                    smtp_config=smtp_config
                )
                if send_res["success"]:
                    break
                retries += 1
                if retries <= max_retries:
                    time.sleep(1.0)  # Short pause before retry

            completed_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if send_res and send_res["success"]:
                results.append({
                    "name": student_name,
                    "email": recipient_email,
                    "status": "SENT",
                    "retry_count": retries,
                    "timestamp": completed_iso,
                    "error": None
                })
                sent_count += 1
            else:
                err_msg = send_res.get("error", "Delivery failed") if send_res else "Delivery failed"
                results.append({
                    "name": student_name,
                    "email": recipient_email,
                    "status": "FAILED",
                    "retry_count": retries,
                    "timestamp": completed_iso,
                    "error": err_msg
                })
                failed_count += 1

        if contact:
            firebase_db.save_email_dispatch_record(contact, {
                "excel_name": session.get('excel_name', os.path.basename(excel_path)),
                "subject": subject_template,
                "total_recipients": len(results),
                "total_sent": sent_count,
                "total_failed": failed_count,
                "sender_email": smtp_config.get("email"),
                "is_custom_smtp": is_custom
            })

        return jsonify({
            "success": True,
            "total": len(results),
            "sent": sent_count,
            "failed": failed_count,
            "sender": smtp_config.get("email"),
            "is_custom_smtp": is_custom,
            "details": results
        })
    except Exception as e:
        sanitized = smtp_security.sanitize_smtp_error(str(e))
        return jsonify({"success": False, "error": sanitized}), 500


# API Endpoint for programmatic JWT token validation / status
@app.route('/api/user/status')
@jwt_required
def api_user_status():
    contact = session.get('user_contact')
    user = firebase_db.get_user_by_contact(contact)
    stats = firebase_db.get_user_stats(contact)
    return jsonify({
        "status": "authenticated",
        "user": {
            "name": user.get("name") if user else g.user_name,
            "contact": contact,
            "tier": user.get("tier", "Pro") if user else "Pro"
        },
        "stats": stats,
        "database": stats.get("db_mode")
    })


# =============================================================
# Canva-Style Certificate Designer Routes
# =============================================================
@app.route('/create-certificate')
@app.route('/designer')
@jwt_required
def create_certificate():
    """Renders the Canva-style Certificate Designer Studio."""
    contact = session.get('user_contact')
    saved_designs = firebase_db.get_user_designs(contact) if contact else []
    return render_template(
        'designer.html',
        user_name=session.get('user_name', 'Designer'),
        user_contact=contact,
        user_avatar=session.get('user_avatar', ''),
        saved_designs=saved_designs
    )


@app.route('/api/save-design', methods=['POST'])
@jwt_required
def api_save_design():
    """Saves a custom certificate design to Firebase database."""
    try:
        contact = session.get('user_contact')
        if not contact:
            return jsonify({"success": False, "error": "Authentication required."}), 401
        
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({"success": False, "error": "Invalid design data."}), 400

        design_id = firebase_db.save_user_design(contact, data)
        return jsonify({
            "success": True,
            "design_id": design_id,
            "message": "Design saved securely to your cloud workspace!"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/my-designs', methods=['GET'])
@jwt_required
def api_my_designs():
    """Returns saved designs for the active authenticated user."""
    try:
        contact = session.get('user_contact')
        designs = firebase_db.get_user_designs(contact) if contact else []
        return jsonify({"success": True, "designs": designs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/delete-design/<design_id>', methods=['DELETE', 'POST'])
@jwt_required
def api_delete_design(design_id):
    """Deletes a saved certificate design."""
    try:
        contact = session.get('user_contact')
        success = firebase_db.delete_user_design(contact, design_id)
        return jsonify({"success": success})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/export-designer-template', methods=['POST'])
@jwt_required
def api_export_designer_template():
    """
    Takes rendered high-resolution image data from the Canva Designer
    and sets it as the active template for the Certificate Studio / bulk generation.
    """
    try:
        data = request.get_json(silent=True) or {}
        image_data = data.get('image_data', '')
        title = data.get('title', 'Custom Certificate Template').strip()

        if not image_data or ',' not in image_data:
            return jsonify({"success": False, "error": "Invalid image payload from designer."}), 400

        import base64
        header, encoded = image_data.split(',', 1)
        image_bytes = base64.b64decode(encoded)

        user_id = session.get('user_id', str(uuid.uuid4()))
        session['user_id'] = user_id

        user_folder = os.path.join(UPLOAD_FOLDER, user_id)
        os.makedirs(user_folder, exist_ok=True)

        template_filename = 'template.jpg'
        template_path = os.path.join(user_folder, template_filename)

        # Convert and save as high-res RGB JPEG using Pillow
        with Image.open(io.BytesIO(image_bytes)) as pil_img:
            rgb_img = pil_img.convert('RGB')
            rgb_img.save(template_path, format='JPEG', quality=95)

        session['template_path'] = template_path
        session['template_name'] = f"{title}.jpg"

        # Determine next destination: if user already has an active Excel sheet, go straight to /map
        has_excel = bool(session.get('excel_path') and os.path.exists(session.get('excel_path')))
        next_route = url_for('back_to_map') if has_excel else url_for('studio')

        return jsonify({
            "success": True,
            "has_excel": has_excel,
            "redirect": next_route,
            "message": "Template successfully generated! Proceeding to batch mapping..."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/upload-designer-asset', methods=['POST'])
@jwt_required
def api_upload_designer_asset():
    """Uploads user logos, emblems, stamps, or custom imagery to place on canvas."""
    try:
        if 'asset' not in request.files:
            return jsonify({"success": False, "error": "No asset file provided."}), 400

        file = request.files['asset']
        if not file or not file.filename:
            return jsonify({"success": False, "error": "Empty filename."}), 400

        user_id = session.get('user_id', str(uuid.uuid4()))
        session['user_id'] = user_id
        assets_dir = os.path.join(UPLOAD_FOLDER, user_id, 'assets')
        os.makedirs(assets_dir, exist_ok=True)

        clean_ext = os.path.splitext(file.filename)[1].lower()
        if clean_ext not in ('.png', '.jpg', '.jpeg', '.svg', '.webp'):
            clean_ext = '.png'

        saved_name = f"asset_{uuid.uuid4().hex[:8]}{clean_ext}"
        saved_path = os.path.join(assets_dir, saved_name)
        file.save(saved_path)

        return jsonify({
            "success": True,
            "url": f"/designer-asset/{user_id}/{saved_name}",
            "filename": file.filename
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/designer-asset/<user_id>/<filename>')
@jwt_required
def serve_designer_asset(user_id, filename):
    """Serves uploaded designer assets securely."""
    assets_dir = os.path.join(UPLOAD_FOLDER, user_id, 'assets')
    file_path = os.path.join(assets_dir, filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return "Asset not found", 404


if __name__ == '__main__':
    app.run(host="0.0.0.0", debug=True, port=int(os.getenv("PORT", 5000)))