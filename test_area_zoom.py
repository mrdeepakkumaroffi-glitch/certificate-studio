import unittest
from flask import render_template
from app import app
import firebase_db

class TestAreaZoomFeature(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.test_contact = "designer_test_user@example.com"
        self.test_password = "Password@123"

        user = firebase_db.get_user_by_contact(self.test_contact)
        if not user:
            firebase_db.create_user(
                contact=self.test_contact,
                name="Canva Designer Pro",
                password=self.test_password,
                email=self.test_contact,
                mobile="+19998887777"
            )

        self.client.post('/login', data={
            'contact': self.test_contact,
            'password': self.test_password
        }, follow_redirects=False)

    def test_designer_area_zoom_elements(self):
        """Verifies that Canva Designer Studio contains all Area Zoom elements and engine."""
        resp = self.client.get('/designer')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check button in floating zoom dock
        self.assertIn('btn-toggle-area-zoom', html)
        self.assertIn('Area Zoom', html)
        self.assertIn('canva-area-zoom-btn', html)

        # Check option in zoom preset dropdown
        self.assertIn('Particular Area Zoom', html)
        self.assertIn('toggleAreaZoomMode()', html)

        # Check floating HUD guide banner
        self.assertIn('id="area-zoom-hud"', html)
        self.assertIn('AREA ZOOM ACTIVE', html)
        self.assertIn('Click any point to magnify, or drag a box over any certificate area', html)

        # Check Marquee & Focus pulse elements
        self.assertIn('id="area-zoom-marquee"', html)
        self.assertIn('id="area-zoom-focus-pulse"', html)

        # Check responsive stage wrapper for smooth scrolling
        self.assertIn('class="canvas-stage" id="canvas-stage"', html)

        # Check Area Zoom JS Engine functions
        self.assertIn('function toggleAreaZoomMode()', html)
        self.assertIn('function enableAreaZoomMode()', html)
        self.assertIn('function disableAreaZoomMode()', html)
        self.assertIn('function zoomAtCertificatePoint(', html)
        self.assertIn('function zoomToCertificateArea(', html)
        self.assertIn('function centerViewportOnCertificateCoord(', html)
        self.assertIn('function initAreaZoomEngine()', html)

        # Check Keyboard Shortcut binding
        self.assertIn("e.key === 'z' || e.key === 'Z'", html)
        print("\n[PASS] Canva Designer Studio Area Zoom UI and Engine verified 100%!")

    def test_map_area_zoom_elements(self):
        """Verifies that Coordinate Studio also contains Area Zoom tool and engine."""
        with app.test_request_context('/map'):
            headers = ['Name', 'College', 'Department']
            sample = {'Name': 'Alice', 'College': 'MIT', 'Department': 'CS'}
            html = render_template('map.html', headers=headers, sample_data=sample)

            # Check Area Zoom button in map zoom controls
            self.assertIn('btn-map-area-zoom', html)
            self.assertIn('toggleMapAreaZoom()', html)
            self.assertIn('centerMapViewportOnCoord', html)
            self.assertIn('isMapAreaZoom', html)
            print("[PASS] Template Mapping Studio Area Zoom verified 100%!")

if __name__ == '__main__':
    unittest.main()
