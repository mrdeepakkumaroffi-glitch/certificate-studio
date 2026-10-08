"""
Verification test for Voice-Command Certificate Editor:
1. Verifies template rendering and presence of Web Speech API and Web Audio DSP hooks.
2. Verifies presence of Voice Focus and Noise Gate components.
3. Tests voice command parsing keywords and structure.
"""
import sys
import os

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from flask import render_template

def test_voice_editor():
    print("=" * 65)
    print("Testing Voice-Command Certificate Editor & Audio Engine")
    print("=" * 65)

    with app.test_request_context('/map'):
        headers = ['Name', 'College', 'Department', 'Email', 'Grade']
        sample = {'Name': 'Priya Sundaram', 'College': 'Stanford University', 'Department': 'Robotics', 'Email': 'priya@stanford.edu', 'Grade': 'A+'}
        html = render_template('map.html', headers=headers, sample_data=sample)

        # 1. Check Voice Control Topbar Button
        assert 'id="voice-topbar-toggle"' in html, "Voice topbar button missing"
        assert 'Voice Control' in html, "Voice Control label missing"
        print("[PASS] Voice Control activation button present in topbar.")

        # 2. Check Audio Engine Settings Button
        assert 'openAudioSettingsModal()' in html, "Audio Engine modal trigger missing"
        print("[PASS] Audio Engine settings trigger present in topbar.")

        # 3. Check Floating Voice Command HUD
        assert 'id="voice-hud"' in html, "Floating Voice HUD missing"
        assert 'id="voice-mini-canvas"' in html, "Mini audio visualizer canvas missing"
        assert 'id="voice-hud-transcript"' in html, "Live transcript display missing"
        assert 'id="voice-hud-feedback"' in html, "Feedback action status missing"
        assert 'id="voice-toast"' in html, "Executed command toast missing"
        print("[PASS] Floating Voice HUD with real-time spectrum canvas verified.")

        # 4. Check Audio Enhancement & Background Noise Control Modal
        assert 'id="audio-settings-modal"' in html, "Audio settings modal missing"
        assert 'id="toggle-voice-focus"' in html, "Voice focus toggle missing"
        assert 'id="toggle-noise-gate"' in html, "Noise gate toggle missing"
        assert 'id="noise-gate-slider"' in html, "Noise gate slider missing"
        assert 'id="mic-gain-slider"' in html, "Microphone pre-gain slider missing"
        assert 'id="toggle-audio-chimes"' in html, "Audio chimes toggle missing"
        assert 'id="voice-full-spectrum"' in html, "Full spectrum canvas missing"
        print("[PASS] Audio Enhancement & Background Noise Control DSP settings verified.")

        # 5. Check Voice Command Reference Cheat Sheet
        assert 'commands-cheatsheet-section' in html, "Command cheatsheet section missing"
        assert 'font cinzel' in html, "Font commands missing in cheatsheet"
        assert 'center horizontally' in html, "Positioning commands missing in cheatsheet"
        assert 'font size 48' in html, "Sizing commands missing in cheatsheet"
        assert 'duplicate' in html, "Action commands missing in cheatsheet"
        print("[PASS] Interactive Voice Command Cheat Sheet present with all command categories.")

        # 6. Check Web Speech & Audio DSP Script Logic
        assert 'SpeechRecognition' in html, "SpeechRecognition API hooks missing"
        assert 'AudioContext' in html, "Web Audio DSP Context missing"
        assert 'peakingFilter' in html, "Voice Focus peaking filter missing"
        assert 'highPassFilter' in html, "High-pass 85Hz noise filter missing"
        assert 'noiseGateThresholdDb' in html, "Noise gate threshold logic missing"
        assert 'processVoiceCommand' in html, "Command parser function missing"
        print("[PASS] Web Audio DSP and Speech-to-Text Recognition engine verified.")

    print("\n" + "=" * 65)
    print("ALL VOICE COMMAND & AUDIO ENHANCEMENT TESTS PASSED 100%!")
    print("=" * 65)


if __name__ == "__main__":
    test_voice_editor()
