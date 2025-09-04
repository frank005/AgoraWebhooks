#!/usr/bin/env python3
"""
Test script to verify webhook parsing for different Agora event types
Based on: https://docs.agora.io/en/video-calling/advanced-features/receive-notifications#event-types
"""

from models import WebhookRequest
import json

def test_webhook_parsing():
    """Test parsing of different webhook event types"""
    
    # Test cases based on Agora documentation
    test_cases = [
        {
            "name": "Event Type 107 - User joined channel (communication profile)",
            "payload": {
                "noticeId": "test-107",
                "productId": 1,
                "eventType": 107,
                "notifyMs": 1757017812147,
                "payload": {
                    "channelName": "test_channel",
                    "uid": 12345,
                    "clientSeq": 67890,
                    "platform": 1,
                    "reason": 1,
                    "ts": 1560496834
                }
            }
        },
        {
            "name": "Event Type 108 - User left channel (communication profile)",
            "payload": {
                "noticeId": "test-108",
                "productId": 1,
                "eventType": 108,
                "notifyMs": 1757017812147,
                "payload": {
                    "channelName": "test_channel",
                    "uid": 12345,
                    "clientSeq": 67891,
                    "platform": 1,
                    "reason": 1,
                    "ts": 1560496834,
                    "duration": 600
                }
            }
        },
        {
            "name": "Event Type 101 - Channel event (no uid/clientSeq)",
            "payload": {
                "noticeId": "test-101",
                "productId": 1,
                "eventType": 101,
                "notifyMs": 1757017812147,
                "payload": {
                    "channelName": "test_webhook",
                    "ts": 1560396834
                }
            }
        },
        {
            "name": "Event Type 111 - Client role change to broadcaster",
            "payload": {
                "noticeId": "test-111",
                "productId": 1,
                "eventType": 111,
                "notifyMs": 1757017812147,
                "payload": {
                    "channelName": "test_webhook",
                    "uid": 12121212,
                    "clientSeq": 1625051035469,
                    "ts": 1560396834
                }
            }
        },
        {
            "name": "Event Type 112 - Client role change to audience",
            "payload": {
                "noticeId": "test-112",
                "productId": 1,
                "eventType": 112,
                "notifyMs": 1757017812147,
                "payload": {
                    "channelName": "test_webhook",
                    "uid": 12121212,
                    "clientSeq": 16250510358369,
                    "ts": 1560496834
                }
            }
        }
    ]
    
    print("🧪 Testing webhook parsing for different Agora event types...")
    print("=" * 60)
    
    for test_case in test_cases:
        try:
            webhook = WebhookRequest(**test_case["payload"])
            print(f"✅ {test_case['name']}")
            print(f"   Event Type: {webhook.eventType}")
            print(f"   Channel: {webhook.payload.channelName}")
            print(f"   UID: {webhook.payload.uid}")
            print(f"   ClientSeq: {webhook.payload.clientSeq}")
            print(f"   Duration: {webhook.payload.duration}")
            print()
        except Exception as e:
            print(f"❌ {test_case['name']}")
            print(f"   Error: {e}")
            print()
    
    print("🎉 Webhook parsing test completed!")

if __name__ == "__main__":
    test_webhook_parsing()
