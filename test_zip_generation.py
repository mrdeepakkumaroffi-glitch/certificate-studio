import sys
import os
import zipfile

# Set UTF-8 encoding
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, render_single_certificate, find_student_name
from auth_jwt import generate_jwt_token
import firebase_db


def test_zip_export():
    print("=" * 60)
    print("Testing Individual PDFs & ZIP Generation Engine")
    print("=" * 60)

    # 1. Test student name detection
    print("\n[Test 1] Testing Student Name Extraction...")
    sample_headers = ["ID", "Name", "Course", "Date"]
    row_1 = [101, "Rahul Sharma", "Python AI", "2026-09-24"]
    row_2 = [102, "Priya Sundaram", "Cloud Computing", "2026-09-24"]
    
    name_1 = find_student_name(row_1, sample_headers, 1)
    name_2 = find_student_name(row_2, sample_headers, 2)
    assert name_1 == "Rahul Sharma", f"Expected Rahul Sharma, got {name_1}"
    assert name_2 == "Priya Sundaram", f"Expected Priya Sundaram, got {name_2}"
    print(f"[PASS] Name extraction: '{name_1}' and '{name_2}' correctly identified.")

    # 2. Test single certificate rendering
    print("\n[Test 2] Testing Single Certificate Image Generation...")
    template_path = "template.jpg"
    assert os.path.exists(template_path), "template.jpg not found"

    test_mappings = [
        {
            "field": "Name",
            "font": "Times New Roman",
            "size": 48,
            "color": "#0f172a",
            "bold": True,
            "italic": False,
            "underline": False,
            "align": "center",
            "caseMode": "none",
            "x": 300,
            "y": 400,
            "w": 500,
            "h": 80
        }
    ]

    img = render_single_certificate(template_path, row_1, sample_headers, test_mappings)
    assert img is not None, "Failed to render certificate image"
    print(f"[PASS] Rendered PIL Image of size: {img.size}")

    # 3. Test HTTP /generate-final endpoint with format=zip
    print("\n[Test 3] Testing Flask ZIP Export Endpoint...")
    client = app.test_client()
    
    # Create test user and session
    user = {"contact": "zip_tester@studio.com", "name": "Zip Tester"}
    token = generate_jwt_token(user)
    client.set_cookie("access_token", token)

    with client.session_transaction() as sess:
        sess["is_logged_in"] = True
        sess["user_contact"] = "zip_tester@studio.com"
        sess["template_path"] = os.path.abspath("template.jpg")
        sess["excel_path"] = os.path.abspath("uploads/students.xlsx")
        sess["mappings"] = test_mappings
        sess["excel_name"] = "students.xlsx"
        sess["template_name"] = "template.jpg"

    resp = client.post("/generate-final", data={"format": "zip"})
    print(f"Status Code: {resp.status_code}")
    print(f"Headers: {dict(resp.headers)}")
    if resp.status_code != 200 or len(resp.data) < 200:
        print(f"Data: {resp.data[:500]}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    
    zip_bytes = resp.data
    assert len(zip_bytes) > 1000, "ZIP file response is unexpectedly small"
    
    # Verify ZIP contents
    import io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        namelist = zf.namelist()
        print(f"[PASS] ZIP Archive verified. Contains {len(namelist)} individual PDFs:")
        for name in namelist:
            print(f"       -> {name}")
            assert name.endswith(".pdf"), f"Expected .pdf extension in ZIP, got {name}"

    # Also test PDF format
    print("\n[Test 4] Testing Flask Combined PDF Export Endpoint...")
    resp_pdf = client.post("/generate-final", data={"format": "pdf"})
    assert resp_pdf.status_code == 200
    assert len(resp_pdf.data) > 1000
    print(f"[PASS] Merged PDF generated successfully ({len(resp_pdf.data)} bytes).")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED! ZIP OF INDIVIDUAL PDFS & MERGED PDF ARE READY.")
    print("=" * 60)


if __name__ == "__main__":
    test_zip_export()
