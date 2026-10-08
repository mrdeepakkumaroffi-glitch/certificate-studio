import io
import json
import base64
from PIL import Image
from app import app
import firebase_db

def test_canva_designer_suite():
    client = app.test_client()

    print("\n--- 1. Testing Unauthenticated Access to Designer ---")
    resp = client.get('/create-certificate', follow_redirects=False)
    assert resp.status_code == 302 and '/login' in resp.headers.get('Location', '')
    print("[PASS] Unauthenticated access to /create-certificate properly redirects to /login.")

    resp = client.get('/designer', follow_redirects=False)
    assert resp.status_code == 302 and '/login' in resp.headers.get('Location', '')
    print("[PASS] Unauthenticated access to /designer properly redirects to /login.")

    print("\n--- 2. Setting up Authenticated Session ---")
    test_contact = "designer_test_user@example.com"
    test_password = "Password@123"
    
    # Ensure test user exists
    user = firebase_db.get_user_by_contact(test_contact)
    if not user:
        firebase_db.create_user(
            contact=test_contact,
            name="Canva Designer Pro",
            password=test_password,
            email=test_contact,
            mobile="+19998887777"
        )

    # Log in
    login_resp = client.post('/login', data={
        'contact': test_contact,
        'password': test_password
    }, follow_redirects=False)
    assert login_resp.status_code in (200, 302)
    print(f"[PASS] Successfully logged in as {test_contact}.")

    print("\n--- 3. Testing GET /create-certificate & /designer ---")
    resp = client.get('/create-certificate')
    assert resp.status_code == 200
    assert b"Canva Certificate Studio" in resp.data
    assert b"certificate_catalog.js" in resp.data
    assert b"btn-bulk-use" in resp.data
    print("[PASS] GET /create-certificate rendered with HTTP 200 and all Canva elements.")

    resp_designer = client.get('/designer')
    assert resp_designer.status_code == 200
    print("[PASS] GET /designer alias also rendered with HTTP 200.")

    print("\n--- 4. Testing POST /api/save-design ---")
    save_payload = {
        "title": "Diploma of AI Innovation",
        "canvas_size": {"width": 1050, "height": 742},
        "aspect_ratio": "landscape-a4",
        "background": {"value": "obsidian_gold", "border": "double_gold"},
        "elements": [
            {
                "id": "el_1",
                "type": "text",
                "text": "CERTIFICATE OF AI MASTERY",
                "x": 100, "y": 120, "width": 800, "height": 60,
                "fontSize": 34, "fontFamily": "Cinzel", "fill": "#d4af37"
            },
            {
                "id": "el_2",
                "type": "svg",
                "svgType": "gold_wax_seal",
                "x": 475, "y": 520, "width": 100, "height": 100
            }
        ],
        "preview_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    }

    save_resp = client.post('/api/save-design', json=save_payload)
    assert save_resp.status_code == 200
    save_data = save_resp.get_json()
    assert save_data.get("success") is True
    design_id = save_data.get("design_id")
    assert design_id is not None
    print(f"[PASS] Successfully saved design project! Assigned ID: {design_id}")

    print("\n--- 5. Testing GET /api/my-designs ---")
    designs_resp = client.get('/api/my-designs')
    assert designs_resp.status_code == 200
    designs_data = designs_resp.get_json()
    assert designs_data.get("success") is True
    saved_list = designs_data.get("designs", [])
    assert any(d.get("id") == design_id for d in saved_list)
    print(f"[PASS] GET /api/my-designs returned user designs including {design_id}.")

    print("\n--- 6. Testing Dashboard Display of Saved Canva Designs ---")
    dash_resp = client.get('/dashboard')
    assert dash_resp.status_code == 200
    assert b"Canva Certificate Designer" in dash_resp.data
    assert b"Saved Canva Projects" in dash_resp.data
    assert b"Diploma of AI Innovation" in dash_resp.data
    print("[PASS] /dashboard displays the newly created Canva design in the Saved Projects gallery!")

    print("\n--- 7. Testing POST /api/export-designer-template (Bulk Excel handoff) ---")
    # Generate a dummy 100x100 RGB PNG in base64
    img = Image.new('RGB', (1050, 742), color=(10, 15, 36))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    encoded_png = base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
    data_uri = f"data:image/png;base64,{encoded_png}"

    export_resp = client.post('/api/export-designer-template', json={
        "image_data": data_uri,
        "title": "Diploma of AI Innovation"
    })
    assert export_resp.status_code == 200
    export_data = export_resp.get_json()
    assert export_data.get("success") is True
    assert "redirect" in export_data
    print(f"[PASS] POST /api/export-designer-template converted design to high-res JPEG and redirected to: {export_data.get('redirect')}")

    with client.session_transaction() as sess:
        assert sess.get('template_path') is not None
        assert 'template.jpg' in sess.get('template_path')
        assert sess.get('template_name') == "Diploma of AI Innovation.jpg"
    print("[PASS] Flask session['template_path'] and session['template_name'] properly set for batch mapping!")

    print("\n--- 8. Testing DELETE /api/delete-design/<design_id> ---")
    del_resp = client.delete(f'/api/delete-design/{design_id}')
    assert del_resp.status_code == 200
    del_data = del_resp.get_json()
    assert del_data.get("success") is True
    print(f"[PASS] Successfully deleted design {design_id}.")

    # Verify deleted
    designs_resp_after = client.get('/api/my-designs')
    assert not any(d.get("id") == design_id for d in designs_resp_after.get_json().get("designs", []))
    print("[PASS] Verified design is completely removed from database.")

    print("\n=======================================================")
    print("[SUCCESS] ALL CANVA CERTIFICATE DESIGNER TESTS PASSED 100%!")
    print("=======================================================")

if __name__ == '__main__':
    test_canva_designer_suite()
