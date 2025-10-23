import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Set
from sqlalchemy.orm import Session
from database import SessionLocal, WebhookEvent, ChannelSession, ChannelMetrics, UserMetrics
from models import WebhookRequest

logger = logging.getLogger(__name__)

class WebhookProcessor:
    """Processes webhook events and updates database"""
    
    def __init__(self):
        self.db = SessionLocal()
        # In-memory cache to track recent noticeIds (max 10 entries)
        self.recent_notice_ids: Set[str] = set()
        self.max_cache_size = 10
    
    def _is_duplicate_webhook(self, notice_id: str) -> bool:
        """Check if this notice_id has been seen recently (in-memory check)"""
        logger.info(f"Checking for duplicate notice_id: {notice_id}")
        logger.info(f"Current cache: {list(self.recent_notice_ids)}")
        
        if notice_id in self.recent_notice_ids:
            logger.warning(f"DUPLICATE WEBHOOK DETECTED for notice_id: {notice_id}")
            return True
        
        logger.info(f"Notice_id {notice_id} is unique")
        return False
    
    def _add_to_cache(self, notice_id: str):
        """Add notice_id to cache, maintaining max size"""
        # If cache is full, remove the oldest entry (FIFO)
        if len(self.recent_notice_ids) >= self.max_cache_size:
            # Convert set to list to remove first element
            notice_ids_list = list(self.recent_notice_ids)
            self.recent_notice_ids.remove(notice_ids_list[0])
        
        # Add new notice_id
        self.recent_notice_ids.add(notice_id)
        logger.debug(f"Added notice_id {notice_id} to cache. Cache size: {len(self.recent_notice_ids)}")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for debugging"""
        return {
            "cache_size": len(self.recent_notice_ids),
            "max_cache_size": self.max_cache_size,
            "recent_notice_ids": list(self.recent_notice_ids)
        }

    async def process_webhook(self, app_id: str, webhook_data: WebhookRequest, raw_payload: str):
        """Process a webhook event and update relevant tables for the specific App ID"""
        try:
            logger.info(f"Processing webhook for App ID: {app_id}, Event Type: {webhook_data.eventType}, Notice ID: {webhook_data.noticeId}")
            
            # Check for duplicates using in-memory cache
            if self._is_duplicate_webhook(webhook_data.noticeId):
                logger.info(f"Skipping duplicate webhook for notice_id: {webhook_data.noticeId}")
                return  # Exit early for duplicates
            
            # Add to cache to prevent future duplicates
            self._add_to_cache(webhook_data.noticeId)
            
            # Store raw webhook event (automatically creates tables if they don't exist)
            await self._store_webhook_event(app_id, webhook_data, raw_payload)
            
            # Process based on event type (only for events with uid and clientSeq)
            if webhook_data.payload.uid is not None and webhook_data.payload.clientSeq is not None:
                if webhook_data.eventType in [103, 105, 107]:  # User joined channel (broadcaster/audience/communication)
                    await self._handle_user_join(app_id, webhook_data)
                elif webhook_data.eventType in [104, 106, 108]:  # User left channel (broadcaster/audience/communication)
                    await self._handle_user_leave(app_id, webhook_data)
            else:
                logger.info(f"Skipping session processing for event type {webhook_data.eventType} - missing uid or clientSeq")
            
            # Update metrics
            await self._update_metrics(app_id, webhook_data)
            
            self.db.commit()
            logger.info(f"Successfully processed webhook for App ID: {app_id}, Event Type: {webhook_data.eventType}")
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error processing webhook for App ID {app_id}: {e}")
            raise
    
    async def _store_webhook_event(self, app_id: str, webhook_data: WebhookRequest, raw_payload: str):
        """Store raw webhook event in database"""
        # Note: Duplicate checking is now handled by in-memory cache in process_webhook()
        
        event = WebhookEvent(
            app_id=app_id,
            notice_id=webhook_data.noticeId,
            product_id=webhook_data.productId,
            event_type=webhook_data.eventType,
            channel_name=webhook_data.payload.channelName,
            uid=webhook_data.payload.uid or 0,  # Default to 0 if uid is None
            client_seq=webhook_data.payload.clientSeq or 0,  # Default to 0 if clientSeq is None
            platform=webhook_data.payload.platform,
            reason=webhook_data.payload.reason,
            ts=webhook_data.payload.ts,
            duration=webhook_data.payload.duration,
            raw_payload=raw_payload
        )
        self.db.add(event)
    
    async def _handle_user_join(self, app_id: str, webhook_data: WebhookRequest):
        """Handle user join event - create new session"""
        join_time = datetime.fromtimestamp(webhook_data.payload.ts)
        
        # Check if there's an existing open session for this user in this channel
        existing_session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == webhook_data.payload.channelName,
            ChannelSession.uid == webhook_data.payload.uid,
            ChannelSession.leave_time.is_(None)
        ).first()
        
        if existing_session:
            # Update existing session join time (reconnection)
            existing_session.join_time = join_time
            existing_session.updated_at = datetime.utcnow()
        else:
            # Create new session
            session = ChannelSession(
                app_id=app_id,
                channel_name=webhook_data.payload.channelName,
                uid=webhook_data.payload.uid,
                join_time=join_time
            )
            self.db.add(session)
            logger.info(f"Created new session for user {webhook_data.payload.uid} in channel {webhook_data.payload.channelName}")
    
    async def _handle_user_leave(self, app_id: str, webhook_data: WebhookRequest):
        """Handle user leave event - close existing session"""
        leave_time = datetime.fromtimestamp(webhook_data.payload.ts)
        
        # Find the most recent open session for this user in this channel
        session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == webhook_data.payload.channelName,
            ChannelSession.uid == webhook_data.payload.uid,
            ChannelSession.leave_time.is_(None)
        ).order_by(ChannelSession.join_time.desc()).first()
        
        if session:
            session.leave_time = leave_time
            session.duration_seconds = int((leave_time - session.join_time).total_seconds())
            session.updated_at = datetime.utcnow()
        else:
            # Create a session with duration from webhook payload if available
            if webhook_data.payload.duration:
                join_time = leave_time - timedelta(seconds=webhook_data.payload.duration)
                session = ChannelSession(
                    app_id=app_id,
                    channel_name=webhook_data.payload.channelName,
                    uid=webhook_data.payload.uid,
                    join_time=join_time,
                    leave_time=leave_time,
                    duration_seconds=webhook_data.payload.duration
                )
                self.db.add(session)
    
    async def _update_metrics(self, app_id: str, webhook_data: WebhookRequest):
        """Update aggregated metrics tables"""
        # This will be called after each webhook to update daily metrics
        # For now, we'll implement a simple version that updates metrics
        # In production, you might want to batch these updates
        
        channel_name = webhook_data.payload.channelName
        uid = webhook_data.payload.uid
        event_date = datetime.fromtimestamp(webhook_data.payload.ts).date()
        event_datetime = datetime.combine(event_date, datetime.min.time())
        
        # Update channel metrics
        await self._update_channel_metrics(app_id, channel_name, event_datetime)
        
        # Update user metrics only if uid is available
        if uid is not None:
            await self._update_user_metrics(app_id, uid, channel_name, event_datetime)
    
    async def _update_channel_metrics(self, app_id: str, channel_name: str, date: datetime):
        """Update or create channel metrics for a specific date"""
        metrics = self.db.query(ChannelMetrics).filter(
            ChannelMetrics.app_id == app_id,
            ChannelMetrics.channel_name == channel_name,
            ChannelMetrics.date == date
        ).first()
        
        # Calculate metrics from both sessions and raw webhook events
        sessions = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name,
            ChannelSession.join_time >= date,
            ChannelSession.join_time < date + timedelta(days=1)
        ).all()
        
        # Also get webhook events for this channel/date to count total activity
        webhook_events = self.db.query(WebhookEvent).filter(
            WebhookEvent.app_id == app_id,
            WebhookEvent.channel_name == channel_name,
            WebhookEvent.ts >= int(date.timestamp()),
            WebhookEvent.ts < int((date + timedelta(days=1)).timestamp())
        ).all()
        
        # Calculate metrics
        total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
        unique_users = len(set(s.uid for s in sessions if s.uid > 0))  # Exclude UID 0
        total_users = len([s for s in sessions if s.uid > 0])  # Exclude UID 0
        
        # If no sessions but we have webhook events, count the events as activity
        if total_users == 0 and len(webhook_events) > 0:
            total_users = len(webhook_events)
            unique_users = len(set(e.uid for e in webhook_events if e.uid > 0))
        
        if not metrics:
            metrics = ChannelMetrics(
                app_id=app_id,
                channel_name=channel_name,
                date=date,
                total_users=total_users,
                total_minutes=total_minutes,
                unique_users=unique_users
            )
            self.db.add(metrics)
        else:
            metrics.total_minutes = total_minutes
            metrics.unique_users = unique_users
            metrics.total_users = total_users
            metrics.updated_at = datetime.utcnow()
    
    async def _update_user_metrics(self, app_id: str, uid: int, channel_name: str, date: datetime):
        """Update or create user metrics for a specific date"""
        metrics = self.db.query(UserMetrics).filter(
            UserMetrics.app_id == app_id,
            UserMetrics.uid == uid,
            UserMetrics.channel_name == channel_name,
            UserMetrics.date == date
        ).first()
        
        if not metrics:
            # Calculate metrics for this user/date
            sessions = self.db.query(ChannelSession).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.uid == uid,
                ChannelSession.channel_name == channel_name,
                ChannelSession.join_time >= date,
                ChannelSession.join_time < date + timedelta(days=1)
            ).all()
            
            total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
            session_count = len(sessions)
            
            metrics = UserMetrics(
                app_id=app_id,
                uid=uid,
                channel_name=channel_name,
                date=date,
                total_minutes=total_minutes,
                session_count=session_count
            )
            self.db.add(metrics)
        else:
            # Recalculate metrics
            sessions = self.db.query(ChannelSession).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.uid == uid,
                ChannelSession.channel_name == channel_name,
                ChannelSession.join_time >= date,
                ChannelSession.join_time < date + timedelta(days=1)
            ).all()
            
            metrics.total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
            metrics.session_count = len(sessions)
            metrics.updated_at = datetime.utcnow()
    
    def close(self):
        """Close database connection"""
        self.db.close()
