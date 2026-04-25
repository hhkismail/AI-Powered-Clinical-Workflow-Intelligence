#!/usr/bin/env python3
"""
Test script for Clinical Notes Automation Backend
Run this after starting the main.py server to test the API
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def test_health_check():
    """Test the health check endpoint"""
    print("\n" + "="*60)
    print("TEST: Health Check")
    print("="*60)
    
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        print("✓ Health check passed")
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        return False
    
    return True


def test_process_note_basic():
    """Test basic note processing"""
    print("\n" + "="*60)
    print("TEST: Process Clinical Note (Basic)")
    print("="*60)
    
    payload = {
        "metadata": {
            "doctor_id": "DR001",
            "patient_id": "PAT12345",
            "department": "Cardiology",
            "timestamp": datetime.now().isoformat() + "Z",
            "priority": "high"
        },
        "payload": {
            "input_methods_used": ["voice_to_text", "manual_entry"],
            "raw_text": "Patient presents with acute chest pain. Troponin levels elevated at 0.5 ng/mL. EKG shows ST elevation in leads II, III, aVF. Vital signs: BP 155/95, HR 102, RR 22. Patient is experiencing diaphoresis and dyspnea. Recommend immediate ICU admission and cardiology consult."
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/process-note",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        print("✓ Note processing test passed")
    except Exception as e:
        print(f"✗ Note processing test failed: {e}")
        return False
    
    return True


def test_process_note_missing_field():
    """Test with missing required field"""
    print("\n" + "="*60)
    print("TEST: Process Note (Missing Field - Should Fail)")
    print("="*60)
    
    payload = {
        "metadata": {
            "doctor_id": "DR001",
            # Missing patient_id
            "department": "Cardiology",
            "timestamp": datetime.now().isoformat() + "Z",
            "priority": "high"
        },
        "payload": {
            "input_methods_used": ["voice_to_text"],
            "raw_text": "Patient presents with chest pain."
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/process-note",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 422  # Validation error
        print("✓ Validation error correctly detected")
    except Exception as e:
        print(f"✗ Validation test failed: {e}")
        return False
    
    return True


def test_process_note_empty_text():
    """Test with empty clinical text"""
    print("\n" + "="*60)
    print("TEST: Process Note (Empty Text)")
    print("="*60)
    
    payload = {
        "metadata": {
            "doctor_id": "DR002",
            "patient_id": "PAT54321",
            "department": "Internal Medicine",
            "timestamp": datetime.now().isoformat() + "Z",
            "priority": "medium"
        },
        "payload": {
            "input_methods_used": ["manual_entry"],
            "raw_text": ""
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/process-note",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        print("✓ Empty text handled gracefully")
    except Exception as e:
        print(f"✗ Empty text test failed: {e}")
        return False
    
    return True


def main():
    """Run all tests"""
    print("\n" + "█"*60)
    print("Clinical Notes Automation Backend - Test Suite")
    print("█"*60)
    print(f"Testing against: {BASE_URL}")
    
    tests = [
        ("Health Check", test_health_check),
        ("Process Note - Basic", test_process_note_basic),
        ("Process Note - Validation", test_process_note_missing_field),
        ("Process Note - Empty Text", test_process_note_empty_text),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' encountered fatal error: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{status:10} - {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Backend is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check implementation.")
    
    return passed == total


if __name__ == "__main__":
    import sys
    
    # Check if server is running
    try:
        requests.get(f"{BASE_URL}/health", timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"\n✗ ERROR: Cannot connect to {BASE_URL}")
        print("Please start the server with: python main.py")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        sys.exit(1)
    
    success = main()
    sys.exit(0 if success else 1)
