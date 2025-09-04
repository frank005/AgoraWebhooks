#!/usr/bin/env python3
"""
Script to recalculate all channel metrics with improved logic
"""

from database import SessionLocal, WebhookEvent, ChannelSession, ChannelMetrics
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def recalculate_all_metrics():
    """Recalculate all channel metrics"""
    db = SessionLocal()
    
    try:
        # Get all unique app_id and channel_name combinations
        channels = db.query(WebhookEvent.app_id, WebhookEvent.channel_name).distinct().all()
        
        logger.info(f"Found {len(channels)} unique channel combinations")
        
        for app_id, channel_name in channels:
            logger.info(f"Processing {app_id}/{channel_name}")
            
            # Get all webhook events for this channel
            events = db.query(WebhookEvent).filter(
                WebhookEvent.app_id == app_id,
                WebhookEvent.channel_name == channel_name
            ).all()
            
            # Group events by date
            events_by_date = {}
            for event in events:
                event_date = datetime.fromtimestamp(event.ts).date()
                if event_date not in events_by_date:
                    events_by_date[event_date] = []
                events_by_date[event_date].append(event)
            
            # Calculate metrics for each date
            for event_date, date_events in events_by_date.items():
                event_datetime = datetime.combine(event_date, datetime.min.time())
                
                # Get sessions for this date
                sessions = db.query(ChannelSession).filter(
                    ChannelSession.app_id == app_id,
                    ChannelSession.channel_name == channel_name,
                    ChannelSession.join_time >= event_datetime,
                    ChannelSession.join_time < event_datetime + timedelta(days=1)
                ).all()
                
                # Calculate metrics
                total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
                unique_users = len(set(s.uid for s in sessions if s.uid > 0))
                total_users = len([s for s in sessions if s.uid > 0])
                
                # If no sessions but we have webhook events, count the events as activity
                if total_users == 0 and len(date_events) > 0:
                    total_users = len(date_events)
                    unique_users = len(set(e.uid for e in date_events if e.uid > 0))
                
                # Update or create metrics
                metrics = db.query(ChannelMetrics).filter(
                    ChannelMetrics.app_id == app_id,
                    ChannelMetrics.channel_name == channel_name,
                    ChannelMetrics.date == event_datetime
                ).first()
                
                if metrics:
                    metrics.total_minutes = total_minutes
                    metrics.unique_users = unique_users
                    metrics.total_users = total_users
                    metrics.updated_at = datetime.utcnow()
                    logger.info(f"  Updated metrics for {event_date}: {total_users} users, {unique_users} unique, {total_minutes:.1f} minutes")
                else:
                    metrics = ChannelMetrics(
                        app_id=app_id,
                        channel_name=channel_name,
                        date=event_datetime,
                        total_users=total_users,
                        total_minutes=total_minutes,
                        unique_users=unique_users
                    )
                    db.add(metrics)
                    logger.info(f"  Created metrics for {event_date}: {total_users} users, {unique_users} unique, {total_minutes:.1f} minutes")
        
        db.commit()
        logger.info("✅ All metrics recalculated successfully!")
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error recalculating metrics: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    recalculate_all_metrics()
