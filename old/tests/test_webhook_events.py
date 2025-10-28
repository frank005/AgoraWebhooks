#!/usr/bin/env python3
"""
Test script for the improved webhook processor
Tests all event types and out-of-order handling
"""

import asyncio
import json
from datetime import datetime
from webhook_processor import WebhookProcessor
from models import WebhookRequest, WebhookPayload

async def test_webhook_events():
    """Test all webhook event types"""
    processor = WebhookProcessor()
    
    # Test data
    app_id = "a9a4b25e4e8b4a558aa39780d1a84342"
    channel_name = "test_channel"
    uid = 12345
    
    # Event types to test
    events = [
        # Channel lifecycle
        {"eventType": 101, "name": "Channel Created", "uid": None, "clientSeq": None},
        {"eventType": 102, "name": "Channel Destroyed", "uid": None, "clientSeq": None},
        
        # User events
        {"eventType": 103, "name": "Broadcaster Join", "uid": uid, "clientSeq": 1},
        {"eventType": 105, "name": "Audience Join", "uid": uid + 1, "clientSeq": 2},
        {"eventType": 107, "name": "Communication Join", "uid": uid + 2, "clientSeq": 3},
        
        # Role changes
        {"eventType": 111, "name": "Role Change to Broadcaster", "uid": uid + 1, "clientSeq": 4},
        {"eventType": 112, "name": "Role Change to Audience", "uid": uid, "clientSeq": 5},
        
        # Leave events
        {"eventType": 104, "name": "Broadcaster Leave", "uid": uid, "clientSeq": 6},
        {"eventType": 106, "name": "Audience Leave", "uid": uid + 1, "clientSeq": 7},
        {"eventType": 108, "name": "Communication Leave", "uid": uid + 2, "clientSeq": 8},
    ]
    
    print("🧪 Testing webhook processor with all event types...")
    
    for i, event in enumerate(events):
        print(f"\n--- Test {i+1}: {event['name']} (Event {event['eventType']}) ---")
        
        # Create webhook data
        webhook_data = WebhookRequest(
            noticeId=f"test_notice_{i}_{int(datetime.now().timestamp())}",
            productId=1,
            eventType=event["eventType"],
            payload=WebhookPayload(
                channelName=channel_name,
                ts=int(datetime.now().timestamp()),
                uid=event["uid"],
                clientSeq=event["clientSeq"],
                platform=1,
                reason=0,
                duration=30 if event["eventType"] in [104, 106, 108] else None
            )
        )
        
        raw_payload = json.dumps(webhook_data.dict())
        
        try:
            await processor.process_webhook(app_id, webhook_data, raw_payload)
            print(f"✅ {event['name']} processed successfully")
        except Exception as e:
            print(f"❌ {event['name']} failed: {e}")
    
    # Test out-of-order events
    print(f"\n--- Testing Out-of-Order Events ---")
    
    # Simulate out-of-order: user leave before join
    print("Testing out-of-order leave before join...")
    leave_time = int(datetime.now().timestamp()) - 100  # 100 seconds ago
    join_time = int(datetime.now().timestamp()) - 50    # 50 seconds ago
    
    # Leave event first (out of order)
    leave_data = WebhookRequest(
        noticeId=f"out_of_order_leave_{int(datetime.now().timestamp())}",
        productId=1,
        eventType=104,  # Broadcaster leave
        payload=WebhookPayload(
            channelName=channel_name,
            ts=leave_time,
            uid=uid + 10,
            clientSeq=100,
            platform=1,
            reason=0,
            duration=30
        )
    )
    
    try:
        await processor.process_webhook(app_id, leave_data, json.dumps(leave_data.dict()))
        print("✅ Out-of-order leave event processed")
    except Exception as e:
        print(f"❌ Out-of-order leave event failed: {e}")
    
    # Join event second (out of order)
    join_data = WebhookRequest(
        noticeId=f"out_of_order_join_{int(datetime.now().timestamp())}",
        productId=1,
        eventType=103,  # Broadcaster join
        payload=WebhookPayload(
            channelName=channel_name,
            ts=join_time,
            uid=uid + 10,
            clientSeq=101,
            platform=1,
            reason=0
        )
    )
    
    try:
        await processor.process_webhook(app_id, join_data, json.dumps(join_data.dict()))
        print("✅ Out-of-order join event processed")
    except Exception as e:
        print(f"❌ Out-of-order join event failed: {e}")
    
    print(f"\n🎉 Webhook processor testing completed!")
    print(f"Check the logs for detailed processing information.")

if __name__ == "__main__":
    asyncio.run(test_webhook_events())