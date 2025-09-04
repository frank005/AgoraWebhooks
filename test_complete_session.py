#!/usr/bin/env python3
"""
Test script to send a complete join/leave session to test duration calculation
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"
APP_ID = "test-session-123"

def send_webhook(event_type, notice_id, uid, channel_name, duration=None):
    """Send a webhook"""
    payload = {
        "noticeId": notice_id,
        "productId": 1,
        "eventType": event_type,
        "notifyMs": int(time.time() * 1000),
        "payload": {
            "channelName": channel_name,
            "uid": uid,
            "clientSeq": int(time.time() * 1000),
            "ts": int(time.time())
        }
    }
    
    if duration:
        payload["payload"]["duration"] = duration
    
    response = requests.post(
        f"{BASE_URL}/{APP_ID}/webhooks",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload)
    )
    
    event_name = "Join" if event_type in [103, 105, 107] else "Leave" if event_type in [104, 106, 108] else f"Event {event_type}"
    print(f"Event {event_type} ({event_name}): {response.status_code}")
    return response.status_code == 200

def test_complete_session():
    """Test a complete user session"""
    print("🧪 Testing complete user session...")
    
    # User joins (communication profile - eventType 107)
    join_success = send_webhook(107, f"test-join-{int(time.time())}", 999, "test_session_channel")
    
    if join_success:
        print("⏳ Waiting 3 seconds...")
        time.sleep(3)
        
        # User leaves with duration (communication profile - eventType 108)
        leave_success = send_webhook(108, f"test-leave-{int(time.time())}", 999, "test_session_channel", duration=180)  # 3 minutes
        
        if leave_success:
            print("✅ Complete session sent successfully")
            
            # Wait a moment for processing
            time.sleep(2)
            
            # Check the results
            response = requests.get(f"{BASE_URL}/api/channels/{APP_ID}")
            if response.status_code == 200:
                data = response.json()
                print("\n📊 Channel data:")
                for channel in data["channels"]:
                    if channel["channel_name"] == "test_session_channel":
                        print(f"  Channel: {channel['channel_name']}")
                        print(f"  Total Minutes: {channel['total_minutes']}")
                        print(f"  Unique Users: {channel['unique_users']}")
                        break
        else:
            print("❌ Failed to send leave event")
    else:
        print("❌ Failed to send join event")

if __name__ == "__main__":
    test_complete_session()
