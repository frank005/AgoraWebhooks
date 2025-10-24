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
        # In-memory cache to track active channel sessions
        self.active_channel_sessions: Dict[str, str] = {}  # {app_id:channel_name -> channel_session_id}
    
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
    
    def _get_or_create_channel_session_id(self, app_id: str, channel_name: str) -> str:
        """Get or create a channel session ID for the given app_id and channel_name"""
        session_key = f"{app_id}:{channel_name}"
        
        # Check if there's an active session
        if session_key in self.active_channel_sessions:
            return self.active_channel_sessions[session_key]
        
        # Create new session ID
        session_id = f"{app_id}_{channel_name}_{int(time.time())}"
        self.active_channel_sessions[session_key] = session_id
        logger.info(f"Created new channel session: {session_key} -> {session_id}")
        return session_id
    
    def _close_channel_session(self, app_id: str, channel_name: str):
        """Close a channel session when channel is destroyed (event 102)"""
        session_key = f"{app_id}:{channel_name}"
        if session_key in self.active_channel_sessions:
            session_id = self.active_channel_sessions[session_key]
            del self.active_channel_sessions[session_key]
            logger.info(f"Closed channel session: {session_key} -> {session_id}")
        else:
            logger.warning(f"Attempted to close non-existent channel session: {session_key}")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for debugging"""
        return {
            "cache_size": len(self.recent_notice_ids),
            "max_cache_size": self.max_cache_size,
            "recent_notice_ids": list(self.recent_notice_ids),
            "active_channel_sessions": self.active_channel_sessions
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
            
            # Handle channel session lifecycle
            channel_session_id = None
            if webhook_data.eventType == 102:  # Channel destroyed
                self._close_channel_session(app_id, webhook_data.payload.channelName)
            elif webhook_data.eventType in [101, 103, 105, 107]:  # Channel created or user joined
                channel_session_id = self._get_or_create_channel_session_id(app_id, webhook_data.payload.channelName)
            
            # Store raw webhook event (automatically creates tables if they don't exist)
            await self._store_webhook_event(app_id, webhook_data, raw_payload, channel_session_id)
            
            # Process based on event type (only for events with uid and clientSeq)
            if webhook_data.payload.uid is not None and webhook_data.payload.clientSeq is not None:
                if webhook_data.eventType in [103, 105, 107]:  # User joined channel (broadcaster/audience/communication)
                    await self._handle_user_join(app_id, webhook_data, channel_session_id)
                elif webhook_data.eventType in [104, 106, 108]:  # User left channel (broadcaster/audience/communication)
                    await self._handle_user_leave(app_id, webhook_data, channel_session_id)
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
    
    async def _store_webhook_event(self, app_id: str, webhook_data: WebhookRequest, raw_payload: str, channel_session_id: str = None):
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
            channel_session_id=channel_session_id,
            raw_payload=raw_payload
        )
        self.db.add(event)
    
    async def _handle_user_join(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Handle user join event - create new session"""
        join_time = datetime.fromtimestamp(webhook_data.payload.ts)
        
        # Check if there's an existing open session for this user in this channel session
        existing_session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == webhook_data.payload.channelName,
            ChannelSession.channel_session_id == channel_session_id,
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
                channel_session_id=channel_session_id,
                uid=webhook_data.payload.uid,
                join_time=join_time
            )
            self.db.add(session)
            logger.info(f"Created new session for user {webhook_data.payload.uid} in channel {webhook_data.payload.channelName} (session: {channel_session_id})")
    
    async def _handle_user_leave(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Handle user leave event - close existing session"""
        leave_time = datetime.fromtimestamp(webhook_data.payload.ts)
        
        # Find the most recent open session for this user in this channel session
        session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == webhook_data.payload.channelName,
            ChannelSession.channel_session_id == channel_session_id,
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
                    channel_session_id=channel_session_id,
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
        
        # Get channel session ID for metrics
        session_key = f"{app_id}:{channel_name}"
        channel_session_id = self.active_channel_sessions.get(session_key)
        
        # Update channel metrics
        await self._update_channel_metrics(app_id, channel_name, event_datetime, channel_session_id)
        
        # Update user metrics only if uid is available
        if uid is not None:
            await self._update_user_metrics(app_id, uid, channel_name, event_datetime, channel_session_id)
    
    async def _update_channel_metrics(self, app_id: str, channel_name: str, date: datetime, channel_session_id: str = None):
        """Update or create channel metrics for a specific date and channel session"""
        metrics = self.db.query(ChannelMetrics).filter(
            ChannelMetrics.app_id == app_id,
            ChannelMetrics.channel_name == channel_name,
            ChannelMetrics.channel_session_id == channel_session_id,
            ChannelMetrics.date == date
        ).first()
        
        # Calculate metrics from both sessions and raw webhook events for this channel session
        sessions = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name,
            ChannelSession.channel_session_id == channel_session_id,
            ChannelSession.join_time >= date,
            ChannelSession.join_time < date + timedelta(days=1)
        ).all()
        
        # Also get webhook events for this channel session/date to count total activity
        webhook_events = self.db.query(WebhookEvent).filter(
            WebhookEvent.app_id == app_id,
            WebhookEvent.channel_name == channel_name,
            WebhookEvent.channel_session_id == channel_session_id,
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
                channel_session_id=channel_session_id,
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
    
    async def _update_user_metrics(self, app_id: str, uid: int, channel_name: str, date: datetime, channel_session_id: str = None):
        """Update or create user metrics for a specific date and channel session"""
        metrics = self.db.query(UserMetrics).filter(
            UserMetrics.app_id == app_id,
            UserMetrics.uid == uid,
            UserMetrics.channel_name == channel_name,
            UserMetrics.channel_session_id == channel_session_id,
            UserMetrics.date == date
        ).first()
        
        if not metrics:
            # Calculate metrics for this user/date/channel session
            sessions = self.db.query(ChannelSession).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.uid == uid,
                ChannelSession.channel_name == channel_name,
                ChannelSession.channel_session_id == channel_session_id,
                ChannelSession.join_time >= date,
                ChannelSession.join_time < date + timedelta(days=1)
            ).all()
            
            total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
            session_count = len(sessions)
            
            metrics = UserMetrics(
                app_id=app_id,
                uid=uid,
                channel_name=channel_name,
                channel_session_id=channel_session_id,
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
                ChannelSession.channel_session_id == channel_session_id,
                ChannelSession.join_time >= date,
                ChannelSession.join_time < date + timedelta(days=1)
            ).all()
            
            metrics.total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
            metrics.session_count = len(sessions)
            metrics.updated_at = datetime.utcnow()
    
    def close(self):
        """Close database connection"""
        self.db.close()
