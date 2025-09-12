#!/usr/bin/env python3
"""
Local test script for UNKNOWN Brain FastAPI application
Run this to test the API endpoints locally before deploying
"""

import requests
import json
import time
from typing import Dict, Any

# Configuration
BASE_URL = "http://localhost:8080"

def test_endpoint(endpoint: str, method: str = "GET", data: Dict[Any, Any] = None) -> bool:
    """Test a single API endpoint"""
    url = f"{BASE_URL}{endpoint}"
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=10)
        else:
            print(f"❌ Unsupported method: {method}")
            return False
        
        if response.status_code == 200:
            print(f"✅ {method} {endpoint} - Status: {response.status_code}")
            return True
        else:
            print(f"❌ {method} {endpoint} - Status: {response.status_code}")
            print(f"   Response: {response.text[:100]}...")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ {method} {endpoint} - Error: {e}")
        return False

def main():
    """Run all API tests"""
    print("🧪 Testing UNKNOWN Brain API locally")
    print("=" * 50)
    
    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"🏥 Server health check: {response.status_code}")
        if response.status_code == 200:
            health_data = response.json()
            print(f"   Service: {health_data.get('service', 'unknown')}")
            print(f"   Environment: {health_data.get('environment', 'unknown')}")
        print()
    except requests.exceptions.RequestException:
        print(f"❌ Cannot connect to server at {BASE_URL}")
        print("💡 Start the server with: uvicorn main:app --host 0.0.0.0 --port 8080")
        return
    
    # Test endpoints
    tests = [
        ("GET", "/", None),
        ("GET", "/health", None),
        ("GET", "/models", None),
        ("GET", "/docs", None),
        # Note: These would need actual data/setup to work properly
        # ("POST", "/process-transcript", {"bucket": "test", "file_path": "test.txt"}),
        # ("POST", "/ingest", {"bucket": "test", "file_path": "test.txt"}),
    ]
    
    passed = 0
    total = len(tests)
    
    for method, endpoint, data in tests:
        if test_endpoint(endpoint, method, data):
            passed += 1
        time.sleep(0.5)  # Small delay between requests
    
    print()
    print(f"📊 Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All tests passed! API is working correctly.")
    else:
        print("⚠️  Some tests failed. Check the server logs for details.")

if __name__ == "__main__":
    main()