#!/usr/bin/env python3
"""
Test script for Agora Webhooks Server
This script sends test webhook requests to verify the server is working correctly.
"""

import requests
import json
import time

# Configuration
BASE_URL = "http://localhost:8000"  # Change to your server URL
APP_ID = "test-app-123"  # Test App ID

def send_test_webhook(event_type: int, channel_name: str, uid: int, duration: int = None):
    """Send a test webhook to the server"""
    
    # Create webhook payload
    payload = {
        "noticeId": f"test-{int(time.time())}",
        "productId": 1,
        "eventType": event_type,
        "payload": {
            "clientSeq": int(time.time() * 1000),
            "uid": uid,
            "channelName": channel_name,
            "platform": 1,
            "reason": 1,
            "ts": int(time.time()),
            "duration": duration
        }
    }
    
    payload_json = json.dumps(payload)
    
    # Send webhook
    url = f"{BASE_URL}/{APP_ID}/webhooks"
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, data=payload_json, headers=headers)
        print(f"✅ Event {event_type} ({'Join' if event_type == 1 else 'Leave'}): {response.status_code}")
        if response.status_code != 200:
            print(f"   Response: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Event {event_type} failed: {e}")
        return False

def test_web_interface():
    """Test the web interface"""
    try:
        response = requests.get(f"{BASE_URL}/")
        print(f"✅ Web interface: {response.status_code}")
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Web interface failed: {e}")
        return False

def test_api_endpoints():
    """Test API endpoints"""
    try:
        # Test channels endpoint
        response = requests.get(f"{BASE_URL}/api/channels/{APP_ID}")
        print(f"✅ Channels API: {response.status_code}")
        
        # Test health endpoint
        response = requests.get(f"{BASE_URL}/health")
        print(f"✅ Health check: {response.status_code}")
        
        return True
    except Exception as e:
        print(f"❌ API endpoints failed: {e}")
        return False

def simulate_user_session():
    """Simulate a complete user session (join and leave)"""
    print("\n🎭 Simulating user session...")
    
    channel_name = f"test-channel-{int(time.time())}"
    uid = 12345
    
    # User joins channel
    print(f"User {uid} joining channel '{channel_name}'...")
    join_success = send_test_webhook(1, channel_name, uid)
    
    if join_success:
        # Wait a bit
        time.sleep(2)
        
        # User leaves channel
        print(f"User {uid} leaving channel '{channel_name}'...")
        leave_success = send_test_webhook(2, channel_name, uid, duration=120)  # 2 minutes
        
        if leave_success:
            print(f"✅ Complete session simulated successfully")
            return channel_name
        else:
            print(f"❌ Failed to simulate user leaving")
    else:
        print(f"❌ Failed to simulate user joining")
    
    return None

def main():
    """Run all tests"""
    print("🧪 Testing Agora Webhooks Server")
    print("=" * 50)
    
    # Test web interface
    print("\n1. Testing web interface...")
    test_web_interface()
    
    # Test API endpoints
    print("\n2. Testing API endpoints...")
    test_api_endpoints()
    
    # Test webhook reception
    print("\n3. Testing webhook reception...")
    
    # Test individual events
    send_test_webhook(1, "test-channel-1", 111, None)  # Join
    time.sleep(1)
    send_test_webhook(2, "test-channel-1", 111, 60)    # Leave after 1 minute
    
    send_test_webhook(1, "test-channel-2", 222, None)  # Join
    time.sleep(1)
    send_test_webhook(2, "test-channel-2", 222, 180)   # Leave after 3 minutes
    
    # Simulate complete session
    channel_name = simulate_user_session()
    
    # Wait for processing
    print("\n⏳ Waiting for webhook processing...")
    time.sleep(3)
    
    # Test data retrieval
    if channel_name:
        print(f"\n4. Testing data retrieval for channel '{channel_name}'...")
        try:
            # Get channels
            response = requests.get(f"{BASE_URL}/api/channels/{APP_ID}")
            if response.status_code == 200:
                channels = response.json().get('channels', [])
                print(f"✅ Found {len(channels)} channels")
                
                # Get channel details
                if channels:
                    test_channel = channels[0]['channel_name']
                    response = requests.get(f"{BASE_URL}/api/channel/{APP_ID}/{test_channel}")
                    if response.status_code == 200:
                        details = response.json()
                        print(f"✅ Channel details: {details['total_minutes']:.1f} minutes, {details['unique_users']} users")
                    else:
                        print(f"❌ Failed to get channel details: {response.status_code}")
            else:
                print(f"❌ Failed to get channels: {response.status_code}")
        except Exception as e:
            print(f"❌ Data retrieval test failed: {e}")
    
    print("\n🎉 Testing completed!")
    print(f"\n📊 View your data at: {BASE_URL}")
    print(f"   Use App ID: {APP_ID}")

if __name__ == "__main__":
    main()
