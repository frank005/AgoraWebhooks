import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Set
from sqlalchemy.orm import Session
from database import SessionLocal, WebhookEvent, ChannelSession, ChannelMetrics, UserMetrics
from models import WebhookRequest
from mappings import log_unknown_values

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
        """Check if this notice_id has been seen recently (in-memory + database check)"""
        logger.info(f"Checking for duplicate notice_id: {notice_id}")
        logger.info(f"Current cache: {list(self.recent_notice_ids)}")
        
        # First check in-memory cache
        if notice_id in self.recent_notice_ids:
            logger.warning(f"DUPLICATE WEBHOOK DETECTED in cache for notice_id: {notice_id}")
            return True
        
        # Also check database for existing notice_id
        existing_event = self.db.query(WebhookEvent).filter(WebhookEvent.notice_id == notice_id).first()
        if existing_event:
            logger.warning(f"DUPLICATE WEBHOOK DETECTED in database for notice_id: {notice_id}")
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
    
    def _get_channel_session_id_for_event(self, app_id: str, webhook_data: WebhookRequest) -> str:
        """Get channel session ID using channel epoch approach"""
        channel_name = webhook_data.payload.channelName
        event_type = webhook_data.eventType
        ts = webhook_data.payload.ts
        
        # Channel lifecycle events
        if event_type == 101:  # Channel created
            # Create new channel epoch using timestamp
            call_id = f"{app_id}_{channel_name}_{ts}"
            session_key = f"{app_id}:{channel_name}"
            self.active_channel_sessions[session_key] = call_id
            logger.info(f"Opened channel epoch: {session_key} -> {call_id}")
            
            # Merge any provisional sessions for this channel
            self._merge_provisional_sessions(app_id, channel_name, call_id)
            
            return call_id
        elif event_type == 102:  # Channel destroyed
            # Close the channel epoch
            session_key = f"{app_id}:{channel_name}"
            call_id = self.active_channel_sessions.get(session_key)
            self._close_channel_session(app_id, channel_name)
            logger.info(f"Closed channel epoch: {session_key} -> {call_id}")
            return call_id
        
        # User events - find the active channel epoch for this channel
        elif event_type in [103, 104, 105, 106, 107, 108, 111, 112]:  # All user events
            session_key = f"{app_id}:{channel_name}"
            
            # First check if there's an active channel epoch
            if session_key in self.active_channel_sessions:
                return self.active_channel_sessions[session_key]
            
            # If no active epoch, find the latest open epoch for this channel
            # This handles out-of-order events where user events come before channel create
            recent_create = self.db.query(WebhookEvent).filter(
                WebhookEvent.app_id == app_id,
                WebhookEvent.channel_name == channel_name,
                WebhookEvent.event_type == 101,  # Channel created
                WebhookEvent.ts <= ts  # Create event before or at this user event
            ).order_by(WebhookEvent.ts.desc()).first()
            
            if recent_create:
                # Check if this create event hasn't been destroyed yet
                destroy_event = self.db.query(WebhookEvent).filter(
                    WebhookEvent.app_id == app_id,
                    WebhookEvent.channel_name == channel_name,
                    WebhookEvent.event_type == 102,  # Channel destroyed
                    WebhookEvent.ts > recent_create.ts,  # Destroy after create
                    WebhookEvent.ts <= ts  # Destroy before or at this user event
                ).first()
                
                if not destroy_event:
                    # Channel is still active, use this epoch
                    call_id = f"{app_id}_{channel_name}_{recent_create.ts}"
                    self.active_channel_sessions[session_key] = call_id
                    logger.info(f"Found active channel epoch for out-of-order event: {session_key} -> {call_id}")
                    return call_id
            
            # If no active epoch found, create a provisional epoch
            # This handles cases where 101/102 events are missing
            call_id = f"{app_id}_{channel_name}_{ts}_provisional"
            self.active_channel_sessions[session_key] = call_id
            logger.info(f"Created provisional channel epoch for out-of-order event: {session_key} -> {call_id}")
            return call_id
        
        return None

    def _close_channel_session(self, app_id: str, channel_name: str):
        """Close a channel session when channel is destroyed (event 102)"""
        session_key = f"{app_id}:{channel_name}"
        if session_key in self.active_channel_sessions:
            session_id = self.active_channel_sessions[session_key]
            del self.active_channel_sessions[session_key]
            logger.info(f"Closed channel session: {session_key} -> {session_id}")
        else:
            logger.warning(f"Attempted to close non-existent channel session: {session_key}")
    
    def _merge_provisional_sessions(self, app_id: str, channel_name: str, correct_session_id: str):
        """Merge provisional sessions into the correct channel session when channel is created"""
        try:
            # Find all provisional sessions for this channel
            provisional_sessions = self.db.query(ChannelSession).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.channel_name == channel_name,
                ChannelSession.channel_session_id.like('%_provisional')
            ).all()
            
            if provisional_sessions:
                logger.info(f"Found {len(provisional_sessions)} provisional sessions to merge for channel {channel_name}")
                
                for session in provisional_sessions:
                    old_session_id = session.channel_session_id
                    session.channel_session_id = correct_session_id
                    session.updated_at = datetime.utcnow()
                    logger.info(f"Merged provisional session {session.id} (UID {session.uid}) from {old_session_id} to {correct_session_id}")
                
                self.db.commit()
                logger.info(f"Successfully merged {len(provisional_sessions)} provisional sessions")
            else:
                logger.debug(f"No provisional sessions found for channel {channel_name}")
                
        except Exception as e:
            logger.error(f"Error merging provisional sessions for {app_id}/{channel_name}: {e}")
            self.db.rollback()

    async def _process_event_by_type(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Process webhook event based on its type"""
        event_type = webhook_data.eventType
        uid = webhook_data.payload.uid
        client_seq = webhook_data.payload.clientSeq
        
        # Log event type for debugging
        event_names = {
            101: "Channel Created",
            102: "Channel Destroyed", 
            103: "Broadcaster Join",
            104: "Broadcaster Leave",
            105: "Audience Join",
            106: "Audience Leave",
            107: "Communication Join",
            108: "Communication Leave",
            111: "Role Change to Broadcaster",
            112: "Role Change to Audience"
        }
        
        event_name = event_names.get(event_type, f"Unknown Event {event_type}")
        logger.info(f"Processing {event_name} for user {uid} in channel {webhook_data.payload.channelName}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
        
        # Handle user events that require uid and clientSeq
        if uid is not None and client_seq is not None:
            if event_type in [103, 105, 107]:  # User joined channel
                await self._handle_user_join(app_id, webhook_data, channel_session_id)
            elif event_type in [104, 106, 108]:  # User left channel
                await self._handle_user_leave(app_id, webhook_data, channel_session_id)
            elif event_type in [111, 112]:  # Role changes
                await self._handle_role_change(app_id, webhook_data, channel_session_id)
        else:
            logger.info(f"Skipping user processing for {event_name} - missing uid ({uid}) or clientSeq ({client_seq})")

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
            logger.info(f"Processing webhook for App ID: {app_id}, Event Type: {webhook_data.eventType}, Notice ID: {webhook_data.noticeId}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
            
            # Check for duplicates using in-memory cache
            if self._is_duplicate_webhook(webhook_data.noticeId):
                logger.info(f"Skipping duplicate webhook for notice_id: {webhook_data.noticeId}")
                return  # Exit early for duplicates
            
            # Add to cache to prevent future duplicates
            self._add_to_cache(webhook_data.noticeId)
            
            # Handle channel session lifecycle
            channel_session_id = self._get_channel_session_id_for_event(app_id, webhook_data)
            
            # Store raw webhook event (automatically creates tables if they don't exist)
            await self._store_webhook_event(app_id, webhook_data, raw_payload, channel_session_id)
            
            # Log unknown values for future mapping
            log_unknown_values(
                webhook_data.payload.platform,
                webhook_data.productId,
                webhook_data.eventType,
                webhook_data.payload.channelName
            )
            
            # Process based on event type
            await self._process_event_by_type(app_id, webhook_data, channel_session_id)
            
            # Update metrics
            await self._update_metrics(app_id, webhook_data, channel_session_id)
            
            self.db.commit()
            logger.info(f"Successfully processed webhook for App ID: {app_id}, Event Type: {webhook_data.eventType}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
            
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
            client_type=webhook_data.payload.clientType,
            ts=webhook_data.payload.ts,
            duration=webhook_data.payload.duration,
            channel_session_id=channel_session_id,
            raw_payload=raw_payload
        )
        self.db.add(event)
    
    async def _handle_user_join(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Handle user join event using clientSeq for proper ordering"""
        join_time = datetime.fromtimestamp(webhook_data.payload.ts)
        uid = webhook_data.payload.uid
        channel_name = webhook_data.payload.channelName
        client_seq = webhook_data.payload.clientSeq
        
        # Check if there's an existing open session for this user in this channel epoch
        existing_session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name,
            ChannelSession.channel_session_id == channel_session_id,
            ChannelSession.uid == uid,
            ChannelSession.leave_time.is_(None)
        ).first()
        
        if existing_session:
            # Check if this is an out-of-order event using clientSeq
            # If clientSeq <= lastClientSeq, ignore (duplicate/old event)
            if hasattr(existing_session, 'last_client_seq') and client_seq <= existing_session.last_client_seq:
                logger.info(f"Ignoring duplicate/old join event for user {uid}, clientSeq {client_seq} <= {existing_session.last_client_seq}")
                return
            
            # If this is a later event, update the session
            if join_time < existing_session.join_time:
                logger.warning(f"Out-of-order join event detected for user {uid}. Existing session starts at {existing_session.join_time}, new event at {join_time}")
                existing_session.join_time = join_time
                existing_session.updated_at = datetime.utcnow()
                logger.info(f"Updated existing session with earlier join time for user {uid}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
            else:
                # Update existing session join time (reconnection)
                existing_session.join_time = join_time
                existing_session.updated_at = datetime.utcnow()
                logger.info(f"Updated existing session join time for user {uid}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
        else:
            # Determine initial role based on event type
            # 103/104: Broadcaster (is_host=True, communication_mode=0)
            # 105/106: Audience (is_host=False, communication_mode=0)  
            # 107/108: Communication (is_host=True, communication_mode=1)
            is_host = event_type in [103, 107]  # Broadcaster join OR Communication join
            communication_mode = 1 if event_type in [107] else 0  # Only communication join
            
            # Create new session
            session = ChannelSession(
                app_id=app_id,
                channel_name=channel_name,
                channel_session_id=channel_session_id,
                uid=uid,
                join_time=join_time,
                product_id=webhook_data.productId,
                platform=webhook_data.payload.platform,
                reason=webhook_data.payload.reason,
                client_type=webhook_data.payload.clientType,
                is_host=is_host,
                communication_mode=communication_mode,
                role_switches=0
            )
            self.db.add(session)
            logger.info(f"Created new session for user {uid} in channel {channel_name} (epoch: {channel_session_id}), Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}, Role: {'Host' if is_host else 'Audience'}")
        
        # Update lastClientSeq for this user
        if existing_session:
            existing_session.last_client_seq = client_seq
            existing_session.updated_at = datetime.utcnow()
    
    async def _handle_user_leave(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Handle user leave event - close existing session with out-of-order handling"""
        leave_time = datetime.fromtimestamp(webhook_data.payload.ts)
        uid = webhook_data.payload.uid
        channel_name = webhook_data.payload.channelName
        
        # Find the most recent open session for this user in this channel
        session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name,
            ChannelSession.uid == uid,
            ChannelSession.leave_time.is_(None)
        ).order_by(ChannelSession.join_time.desc()).first()
        
        if session:
            # Check if this is an out-of-order event (leave time is before join time)
            if leave_time < session.join_time:
                logger.warning(f"Out-of-order leave event detected for user {uid}. Session starts at {session.join_time}, leave event at {leave_time}")
                # Adjust the join time to be before the leave time
                session.join_time = leave_time - timedelta(seconds=webhook_data.payload.duration or 0)
                logger.info(f"Adjusted session join time for out-of-order leave event")
            
            session.leave_time = leave_time
            session.duration_seconds = int((leave_time - session.join_time).total_seconds())
            # Update reason from leave event
            session.reason = webhook_data.payload.reason
            session.updated_at = datetime.utcnow()
            logger.info(f"Closed session for user {uid} with duration {session.duration_seconds} seconds, reason: {session.reason}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}")
        else:
            # Create a session with duration from webhook payload if available
            if webhook_data.payload.duration:
                join_time = leave_time - timedelta(seconds=webhook_data.payload.duration)
                session = ChannelSession(
                    app_id=app_id,
                    channel_name=channel_name,
                    channel_session_id=channel_session_id,
                    uid=uid,
                    join_time=join_time,
                    leave_time=leave_time,
                    duration_seconds=webhook_data.payload.duration,
                    product_id=webhook_data.productId,
                    platform=webhook_data.payload.platform,
                    reason=webhook_data.payload.reason,
                    client_type=webhook_data.payload.clientType
                )
                self.db.add(session)
                logger.info(f"Created session from leave event for user {uid} with duration {webhook_data.payload.duration} seconds, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
            else:
                logger.warning(f"No open session found for user {uid} leave event and no duration provided")

    async def _handle_role_change(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Handle role change events (111, 112) - track role switches and communication mode"""
        uid = webhook_data.payload.uid
        channel_name = webhook_data.payload.channelName
        event_type = webhook_data.eventType
        ts = datetime.fromtimestamp(webhook_data.payload.ts)
        
        # 111: client role change to broadcaster
        # 112: client role change to audience
        # Role switches only happen between broadcaster and audience (not communication mode)
        role_change_type = "Broadcaster" if event_type == 111 else "Audience"
        is_host = event_type == 111
        # Role switches preserve the existing communication_mode (0 for broadcaster/audience)
        communication_mode = 0  # Role switches are always in broadcaster/audience mode
        
        logger.info(f"Role change event: User {uid} changed to {role_change_type} in channel {channel_name} at {ts}, Product ID: {webhook_data.productId}, Platform: {webhook_data.payload.platform}, Reason: {webhook_data.payload.reason}")
        
        # Find the active session for this user and update role information
        active_session = self.db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name,
            ChannelSession.channel_session_id == channel_session_id,
            ChannelSession.uid == uid,
            ChannelSession.leave_time.is_(None)
        ).first()
        
        if active_session:
            # Update role information
            active_session.is_host = is_host
            # Role switches are always in broadcaster/audience mode (communication_mode=0)
            active_session.communication_mode = communication_mode
            active_session.role_switches += 1
            active_session.updated_at = datetime.utcnow()
            logger.info(f"Updated role for user {uid}: is_host={is_host}, communication_mode={communication_mode}, role_switches={active_session.role_switches}")
        else:
            logger.warning(f"No active session found for role change event for user {uid} in channel {channel_name}")
    
    async def _update_metrics(self, app_id: str, webhook_data: WebhookRequest, channel_session_id: str = None):
        """Update aggregated metrics tables"""
        # This will be called after each webhook to update daily metrics
        # For now, we'll implement a simple version that updates metrics
        # In production, you might want to batch these updates
        
        channel_name = webhook_data.payload.channelName
        uid = webhook_data.payload.uid
        event_date = datetime.fromtimestamp(webhook_data.payload.ts).date()
        event_datetime = datetime.combine(event_date, datetime.min.time())
        
        # Use the channel_session_id passed from the main processing function
        # This ensures we have the correct session ID even for channel destroy events
        if channel_session_id is None:
            # Fallback: try to get from active sessions (for backward compatibility)
            session_key = f"{app_id}:{channel_name}"
            channel_session_id = self.active_channel_sessions.get(session_key)
        
        # Update channel metrics
        await self._update_channel_metrics(app_id, channel_name, event_datetime, channel_session_id)
        
        # Update user metrics only if uid is available
        if uid is not None:
            await self._update_user_metrics(app_id, uid, channel_name, event_datetime, channel_session_id)
    
    async def _update_channel_metrics(self, app_id: str, channel_name: str, date: datetime, channel_session_id: str = None):
        """Update or create channel metrics for a specific date and channel session"""
        # First, try to find existing metrics for this exact combination
        metrics = self.db.query(ChannelMetrics).filter(
            ChannelMetrics.app_id == app_id,
            ChannelMetrics.channel_name == channel_name,
            ChannelMetrics.channel_session_id == channel_session_id,
            ChannelMetrics.date == date
        ).first()
        
        # If not found, we'll create a new metrics record
        # Each channel session should have its own metrics record
        
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
        
        # Calculate first and last activity timestamps
        first_activity = None
        last_activity = None
        
        # Get first activity from webhook events (channel create)
        channel_create_events = self.db.query(WebhookEvent).filter(
            WebhookEvent.app_id == app_id,
            WebhookEvent.channel_name == channel_name,
            WebhookEvent.channel_session_id == channel_session_id,
            WebhookEvent.event_type == 101,  # channel_created
            WebhookEvent.ts >= int(date.timestamp()),
            WebhookEvent.ts < int((date + timedelta(days=1)).timestamp())
        ).order_by(WebhookEvent.ts).first()
        
        if channel_create_events:
            first_activity = datetime.fromtimestamp(channel_create_events.ts)
        
        # Get last activity from webhook events (channel destroy or last user leave)
        last_events = self.db.query(WebhookEvent).filter(
            WebhookEvent.app_id == app_id,
            WebhookEvent.channel_name == channel_name,
            WebhookEvent.channel_session_id == channel_session_id,
            WebhookEvent.event_type.in_([102, 104, 106, 108]),  # channel_destroyed, broadcaster_leave, audience_leave, communication_leave
            WebhookEvent.ts >= int(date.timestamp()),
            WebhookEvent.ts < int((date + timedelta(days=1)).timestamp())
        ).order_by(WebhookEvent.ts.desc()).first()
        
        if last_events:
            last_activity = datetime.fromtimestamp(last_events.ts)
        
        # If no sessions but we have webhook events, count the events as activity
        if total_users == 0 and len(webhook_events) > 0:
            total_users = len(webhook_events)
            unique_users = len(set(e.uid for e in webhook_events if e.uid > 0))
        
        if not metrics:
            # Create new metrics record
            metrics = ChannelMetrics(
                app_id=app_id,
                channel_name=channel_name,
                channel_session_id=channel_session_id,
                date=date,
                total_users=total_users,
                total_minutes=total_minutes,
                unique_users=unique_users,
                first_activity=first_activity,
                last_activity=last_activity
            )
            self.db.add(metrics)
        else:
            # Update existing metrics - recalculate from scratch to avoid double counting
            # This ensures we get the correct totals even if called multiple times
            metrics.total_minutes = total_minutes
            metrics.total_users = total_users
            metrics.unique_users = unique_users
            
            # Update activity timestamps
            if first_activity and (not metrics.first_activity or first_activity < metrics.first_activity):
                metrics.first_activity = first_activity
            if last_activity and (not metrics.last_activity or last_activity > metrics.last_activity):
                metrics.last_activity = last_activity
            
            metrics.updated_at = datetime.utcnow()
    
    async def _update_user_metrics(self, app_id: str, uid: int, channel_name: str, date: datetime, channel_session_id: str = None):
        """Update or create user metrics for a specific date and channel session"""
        # First, try to find existing metrics for this exact combination
        metrics = self.db.query(UserMetrics).filter(
            UserMetrics.app_id == app_id,
            UserMetrics.uid == uid,
            UserMetrics.channel_name == channel_name,
            UserMetrics.channel_session_id == channel_session_id,
            UserMetrics.date == date
        ).first()
        
        # If not found, try to find metrics for the same app_id, uid, channel_name, and date but different channel_session_id
        if not metrics:
            metrics = self.db.query(UserMetrics).filter(
                UserMetrics.app_id == app_id,
                UserMetrics.uid == uid,
                UserMetrics.channel_name == channel_name,
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
            # Recalculate metrics for all sessions for this user/date/channel
            all_sessions = self.db.query(ChannelSession).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.uid == uid,
                ChannelSession.channel_name == channel_name,
                ChannelSession.join_time >= date,
                ChannelSession.join_time < date + timedelta(days=1)
            ).all()
            
            metrics.total_minutes = sum(s.duration_seconds or 0 for s in all_sessions) / 60.0
            metrics.session_count = len(all_sessions)
            metrics.updated_at = datetime.utcnow()
    
    def close(self):
        """Close database connection"""
        self.db.close()
