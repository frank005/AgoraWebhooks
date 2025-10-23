#!/usr/bin/env python3
"""
Test script to verify duplicate webhook prevention
This script sends duplicate webhooks to test the in-memory cache functionality.
"""

import requests
import json
import time

# Configuration
BASE_URL = "http://localhost:8000"
APP_ID = "test-app-123"

def send_webhook(notice_id: str, event_type: int, channel_name: str, uid: int):
    """Send a webhook with specific notice_id"""
    
    payload = {
        "noticeId": notice_id,
        "productId": 1,
        "eventType": event_type,
        "payload": {
            "clientSeq": int(time.time() * 1000),
            "uid": uid,
            "channelName": channel_name,
            "platform": 1,
            "reason": 1,
            "ts": int(time.time()),
            "duration": None
        }
    }
    
    url = f"{BASE_URL}/{APP_ID}/webhooks"
    headers = {"Content-Type": "application/json"}
    
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers)
        print(f"Webhook {notice_id}: Status {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"Webhook {notice_id} failed: {e}")
        return False

def test_duplicate_prevention():
    """Test that duplicate webhooks are properly handled"""
    print("🧪 Testing Duplicate Webhook Prevention")
    print("=" * 50)
    
    # Test 1: Send unique webhooks
    print("\n1. Sending unique webhooks...")
    unique_notice_ids = [
        "unique-1", "unique-2", "unique-3", "unique-4", "unique-5"
    ]
    
    for notice_id in unique_notice_ids:
        send_webhook(notice_id, 103, "test-channel", 111)
        time.sleep(0.1)  # Small delay between requests
    
    # Test 2: Send duplicate webhooks (should be rejected)
    print("\n2. Sending duplicate webhooks (should be rejected)...")
    duplicate_notice_ids = [
        "unique-1", "unique-2", "unique-3"  # These should be duplicates
    ]
    
    for notice_id in duplicate_notice_ids:
        send_webhook(notice_id, 103, "test-channel", 111)
        time.sleep(0.1)
    
    # Test 3: Send new unique webhooks (should work)
    print("\n3. Sending new unique webhooks...")
    new_unique_notice_ids = [
        "new-unique-1", "new-unique-2", "new-unique-3"
    ]
    
    for notice_id in new_unique_notice_ids:
        send_webhook(notice_id, 103, "test-channel", 111)
        time.sleep(0.1)
    
    # Test 4: Fill cache beyond max size (should evict oldest)
    print("\n4. Testing cache eviction (filling beyond max size)...")
    overflow_notice_ids = [
        "overflow-1", "overflow-2", "overflow-3", "overflow-4", "overflow-5",
        "overflow-6", "overflow-7", "overflow-8", "overflow-9", "overflow-10"
    ]
    
    for notice_id in overflow_notice_ids:
        send_webhook(notice_id, 103, "test-channel", 111)
        time.sleep(0.1)
    
    # Test 5: Try to reuse very old notice_id (should work since it was evicted)
    print("\n5. Testing cache eviction - reusing old notice_id...")
    send_webhook("unique-1", 103, "test-channel", 111)  # This should work now
    
    print("\n✅ Duplicate prevention test completed!")
    print(f"\n📊 Check the server logs to see:")
    print(f"   - 'Duplicate webhook detected' messages for rejected duplicates")
    print(f"   - 'Added notice_id X to cache' messages for new webhooks")
    print(f"   - Cache size changes as webhooks are processed")

if __name__ == "__main__":
    test_duplicate_prevention()
