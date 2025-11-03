import asyncio
import json
import logging
import time
import functools
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, or_
import uvicorn

from config import Config
from database import get_db, create_tables, ChannelSession, ChannelMetrics, UserMetrics, WebhookEvent, RoleEvent
from models import WebhookRequest, ChannelSessionResponse, ChannelMetricsResponse, UserMetricsResponse, ChannelListResponse, ChannelDetailResponse, ExportRequest, ExportResponse, UserDetailResponse, RoleAnalyticsResponse, QualityMetricsResponse, MinutesAnalyticsRequest, MinutesAnalyticsResponse
from webhook_processor import WebhookProcessor
from export_service import ExportService
from security import SecurityConfig, rate_limiter, get_rate_limit_headers, WebhookValidator, ExportSecurity

# Configure logging
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def calculate_role_minutes_from_events(sessions, role_events, channel_session_id, db=None):
    """Calculate host/audience minutes by splitting user presence segments at role changes"""
    host_minutes = 0.0
    audience_minutes = 0.0
    
    # Group sessions by user
    user_sessions = {}
    for session in sessions:
        if session.uid not in user_sessions:
            user_sessions[session.uid] = []
        user_sessions[session.uid].append(session)
    
    # Process each user's sessions
    for uid, user_session_list in user_sessions.items():
        # Get role events for this user in this channel session, sorted by timestamp
        user_role_events = [
            re for re in role_events 
            if re.uid == uid and re.channel_session_id == channel_session_id
        ]
        user_role_events.sort(key=lambda x: x.ts)
        
        # Process each session for this user
        for session in user_session_list:
            if not session.join_time or not session.leave_time:
                continue
            
            join_ts = int(session.join_time.timestamp())
            leave_ts = int(session.leave_time.timestamp())
            
            # Get role events that occurred during this session
            session_role_events = [
                re for re in user_role_events
                if join_ts <= re.ts <= leave_ts
            ]
            
            # Determine initial role: look at join webhook event if available, otherwise infer from first role event
            initial_role = None
            if db:
                # Try to find the join event for this session
                join_event = db.query(WebhookEvent).filter(
                    WebhookEvent.app_id == session.app_id,
                    WebhookEvent.channel_name == session.channel_name,
                    WebhookEvent.channel_session_id == channel_session_id,
                    WebhookEvent.uid == uid,
                    WebhookEvent.event_type.in_([103, 105, 107]),  # Join events
                    WebhookEvent.ts >= join_ts - 5,  # Allow small time difference
                    WebhookEvent.ts <= join_ts + 5
                ).order_by(WebhookEvent.ts).first()
                
                if join_event:
                    # 103/107 = host, 105 = audience
                    initial_role = 'host' if join_event.event_type in [103, 107] else 'audience'
            
            # If couldn't determine from join event, infer from first role event or use session.is_host
            if initial_role is None:
                if session_role_events:
                    # If first role event switches TO host (111), initial was audience
                    # If first role event switches TO audience (112), initial was host
                    first_event = session_role_events[0]
                    initial_role = 'audience' if first_event.new_role == 111 else 'host'
                else:
                    # No role events, use session.is_host (which should reflect initial role)
                    initial_role = 'host' if session.is_host else 'audience'
            
            # If no role events, use the entire session duration with initial role
            if not session_role_events:
                duration_minutes = (session.duration_seconds or 0) / 60.0
                if initial_role == 'host':
                    host_minutes += duration_minutes
                else:
                    audience_minutes += duration_minutes
                continue
            
            # Split session at role change points
            current_role = initial_role
            last_ts = join_ts
            for role_event in session_role_events:
                # Calculate duration from last_ts to this role event
                if last_ts < role_event.ts:
                    segment_duration = (role_event.ts - last_ts) / 60.0
                    if current_role == 'host':
                        host_minutes += segment_duration
                    else:
                        audience_minutes += segment_duration
                    
                    last_ts = role_event.ts
                
                # Update current role based on event
                current_role = 'host' if role_event.new_role == 111 else 'audience'
            
            # Add remaining segment from last role event to leave
            if last_ts < leave_ts:
                segment_duration = (leave_ts - last_ts) / 60.0
                if current_role == 'host':
                    host_minutes += segment_duration
                else:
                    audience_minutes += segment_duration
    
    return host_minutes, audience_minutes

def calculate_max_concurrency(sessions):
    """Calculate max concurrent users from join/leave pairs"""
    if not sessions:
        return 0, None, []
    
    # Collect all join/leave events with timestamps
    events = []
    for session in sessions:
        if session.join_time:
            events.append(('join', session.join_time.timestamp(), session.uid))
        if session.leave_time:
            events.append(('leave', session.leave_time.timestamp(), session.uid))
    
    if not events:
        return 0, None, []
    
    # Sort events by timestamp
    events.sort(key=lambda x: x[1])
    
    # Track concurrent users at each point
    active_users = set()
    max_concurrent = 0
    peak_time = None
    concurrency_over_time = []  # List of (timestamp, count) tuples
    
    for event_type, timestamp, uid in events:
        if event_type == 'join':
            active_users.add(uid)
        else:  # leave
            active_users.discard(uid)
        
        current_count = len(active_users)
        concurrency_over_time.append((timestamp, current_count))
        
        if current_count > max_concurrent:
            max_concurrent = current_count
            peak_time = datetime.fromtimestamp(timestamp)
    
    return max_concurrent, peak_time, concurrency_over_time

def analyze_user_reconnection_patterns(sessions, uid):
    """Analyze user reconnection patterns and burst behavior within the same call"""
    if not sessions:
        return {
            'reconnection_count': 0,
            'burst_sessions': 0,
            'rapid_reconnections': 0,
            'avg_session_gap_minutes': 0,
            'reconnection_pattern': 'stable'
        }
    
    # Sort sessions by join time
    sorted_sessions = sorted(sessions, key=lambda s: s.join_time)
    
    reconnection_count = 0
    burst_sessions = 0
    rapid_reconnections = 0
    session_gaps = []
    
    # Group sessions by channel_session_id to analyze within the same call
    channel_sessions = {}
    for session in sorted_sessions:
        channel_key = session.channel_session_id
        if channel_key not in channel_sessions:
            channel_sessions[channel_key] = []
        channel_sessions[channel_key].append(session)
    
    # Analyze each channel session
    for channel_key, channel_sessions_list in channel_sessions.items():
        if len(channel_sessions_list) <= 1:
            continue  # No reconnections in this channel
            
        # Sort by join time within this channel
        channel_sessions_list.sort(key=lambda s: s.join_time)
        
        # Count reconnections (multiple sessions in same channel = reconnections)
        reconnection_count += len(channel_sessions_list) - 1
        
        # Analyze gaps between sessions
        for i in range(1, len(channel_sessions_list)):
            prev_session = channel_sessions_list[i-1]
            curr_session = channel_sessions_list[i]
            
            # Calculate gap between sessions
            if prev_session.leave_time and curr_session.join_time:
                gap_minutes = (curr_session.join_time - prev_session.leave_time).total_seconds() / 60.0
                session_gaps.append(gap_minutes)
                
                # Rapid reconnection (within 2 minutes)
                if gap_minutes <= 2:
                    rapid_reconnections += 1
                    
                # Burst pattern (within 30 seconds)
                if gap_minutes <= 0.5:
                    burst_sessions += 1
    
    # Calculate average gap
    avg_session_gap_minutes = sum(session_gaps) / len(session_gaps) if session_gaps else 0
    
    # Determine reconnection pattern
    if rapid_reconnections >= 3:
        pattern = 'unstable'
    elif rapid_reconnections >= 1:
        pattern = 'moderate'
    elif reconnection_count > 0:
        pattern = 'stable'
    else:
        pattern = 'no_reconnections'
    
    return {
        'reconnection_count': reconnection_count,
        'burst_sessions': burst_sessions,
        'rapid_reconnections': rapid_reconnections,
        'avg_session_gap_minutes': round(avg_session_gap_minutes, 2),
        'reconnection_pattern': pattern
    }

# Initialize webhook processor
webhook_processor = WebhookProcessor()

# Webhook signature verification has been removed for simplified processing

# Create FastAPI app
app = FastAPI(title="Agora Webhooks Server", version="1.0.0")

# Ensure UTF-8 encoding for JSON responses
from fastapi.responses import JSONResponse as FastAPIJSONResponse
import json as json_lib

class UTF8JSONResponse(FastAPIJSONResponse):
    def render(self, content) -> bytes:
        json_str = json_lib.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=str
        )
        return json_str.encode("utf-8")

app.default_response_class = UTF8JSONResponse

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting storage (in production, use Redis or similar)
rate_limit_storage = {}

# Rate limiting decorator
def rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """Simple rate limiting decorator"""
    def decorator(func):
        import functools
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Get client IP from Request object
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            # Also check kwargs for Request
            if not request:
                for key, value in kwargs.items():
                    if isinstance(value, Request):
                        request = value
                        break
            
            if not request:
                # If no Request found, try to get it from Depends
                # This shouldn't happen, but handle gracefully
                return await func(*args, **kwargs)
            
            client_ip = request.client.host if request.client else "unknown"
            current_time = time.time()
            
            # Clean old entries
            cutoff_time = current_time - window_seconds
            rate_limit_storage[client_ip] = [
                timestamp for timestamp in rate_limit_storage.get(client_ip, [])
                if timestamp > cutoff_time
            ]
            
            # Check rate limit
            if len(rate_limit_storage.get(client_ip, [])) >= max_requests:
                raise HTTPException(
                    status_code=429, 
                    detail=f"Rate limit exceeded: {max_requests} requests per {window_seconds} seconds"
                )
            
            # Add current request
            if client_ip not in rate_limit_storage:
                rate_limit_storage[client_ip] = []
            rate_limit_storage[client_ip].append(current_time)
            
            return await func(*args, **kwargs)
        return wrapper
    return decorator

# Security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    
    # Add security headers from config
    for header, value in SecurityConfig.SECURITY_HEADERS.items():
        response.headers[header] = value
    
    return response

# Initialize database on startup
create_tables()
logger.info("Database tables created/verified")

# Templates for web interface
templates = Jinja2Templates(directory="templates")

@app.post("/{app_id}/webhooks")
# @rate_limit(max_requests=1000, window_seconds=60)  # Temporarily disabled for testing
async def receive_webhook(app_id: str, request: Request):
    """Receive webhook from Agora for specific App ID"""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.info(f"Received webhook from {client_ip} for app_id: {app_id}, User-Agent: {user_agent}")
    
    try:
        # Validate App ID
        if not WebhookValidator.validate_app_id(app_id):
            logger.warning(f"Invalid App ID format: {app_id}")
            raise HTTPException(status_code=400, detail="Invalid App ID format")
        
        # Get raw body
        body = await request.body()
        logger.debug(f"Webhook body length: {len(body)} bytes")
        
        # Validate payload size
        if not WebhookValidator.validate_payload_size(body.decode('utf-8')):
            logger.warning(f"Payload too large from {client_ip}")
            raise HTTPException(status_code=413, detail="Payload too large")
        
        # Parse webhook data
        try:
            webhook_data = WebhookRequest.parse_raw(body)
            logger.debug(f"Parsed webhook: noticeId={webhook_data.noticeId}, eventType={webhook_data.eventType}")
        except Exception as e:
            logger.error(f"Failed to parse webhook data from {client_ip}: {e}")
            logger.error(f"Raw body: {body.decode('utf-8', errors='ignore')[:500]}")
            raise HTTPException(status_code=400, detail="Invalid webhook data")
        
        # Process webhook asynchronously
        await webhook_processor.process_webhook(app_id, webhook_data, body.decode('utf-8'))
        
        logger.info(f"Webhook processed successfully for app_id: {app_id}, event_type: {webhook_data.eventType}, product_id: {webhook_data.productId}, platform: {webhook_data.payload.platform}, reason: {webhook_data.payload.reason}, from: {client_ip}")
        return JSONResponse(content={"status": "success", "message": "Webhook processed"})
        
    except HTTPException as he:
        logger.error(f"HTTP error processing webhook from {client_ip} for app_id {app_id}: {he.detail}")
        raise
    except Exception as e:
        logger.error(f"Error processing webhook for app_id {app_id} from {client_ip}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/", response_class=HTMLResponse)
async def web_interface(request: Request):
    """Main web interface for querying data"""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/channels/{app_id}")
async def get_channels(app_id: str, page: int = 1, per_page: int = 30, db: Session = Depends(get_db)):
    """Get list of channels for an App ID with pagination"""
    try:
        # Calculate total count using subquery
        subquery = db.query(
            ChannelSession.channel_name,
            ChannelSession.channel_session_id
        ).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.duration_seconds.isnot(None)  # Only include completed sessions
        ).group_by(ChannelSession.channel_name, ChannelSession.channel_session_id).subquery()
        
        total_count = db.query(func.count()).select_from(subquery).scalar()
        
        # Calculate offset for pagination
        offset = (page - 1) * per_page
        
        # Calculate metrics directly from channel sessions to ensure accuracy
        channel_sessions = db.query(
            ChannelSession.channel_name,
            ChannelSession.channel_session_id,
            func.sum(ChannelSession.duration_seconds).label('total_seconds'),
            func.count(func.distinct(ChannelSession.uid)).label('unique_users'),
            func.min(ChannelSession.join_time).label('first_activity'),
            func.max(ChannelSession.leave_time).label('last_activity')
        ).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.duration_seconds.isnot(None)  # Only include completed sessions
        ).group_by(ChannelSession.channel_name, ChannelSession.channel_session_id).order_by(desc('last_activity')).offset(offset).limit(per_page).all()
        
        # Get client types for each channel session separately (SQLite compatible)
        channel_client_types = {}
        for session in channel_sessions:
            key = (session.channel_name, session.channel_session_id)
            client_types = db.query(ChannelSession.client_type).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.channel_name == session.channel_name,
                ChannelSession.channel_session_id == session.channel_session_id,
                ChannelSession.client_type.isnot(None)
            ).distinct().all()
            channel_client_types[key] = [ct[0] for ct in client_types if ct[0] is not None]
        
        channels = []
        for session in channel_sessions:
            # Keep channel name simple - no time ranges in the name
            display_name = session.channel_name
            
            # Convert seconds to minutes
            total_minutes = (session.total_seconds or 0) / 60.0
            
            # Get client types for this channel session
            key = (session.channel_name, session.channel_session_id)
            client_types = channel_client_types.get(key, [])
            
            channels.append(ChannelListResponse(
                channel_name=session.channel_name,
                display_name=display_name,
                channel_session_id=session.channel_session_id,
                total_minutes=float(total_minutes),
                unique_users=session.unique_users or 0,
                first_activity=session.first_activity,
                last_activity=session.last_activity,
                client_types=client_types if client_types else None
            ))
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        has_next = page < total_pages
        has_prev = page > 1
        
        return {
            "channels": channels,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": total_count,
                "total_pages": total_pages,
                "has_next": has_next,
                "has_prev": has_prev
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting channels for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/channel/{app_id}/{channel_name}")
async def get_channel_details(app_id: str, channel_name: str, session_id: str = None, db: Session = Depends(get_db)):
    """Get detailed information for a specific channel session"""
    try:
        # Get channel sessions for the specific session ID
        query = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name
        )
        
        if session_id:
            query = query.filter(ChannelSession.channel_session_id == session_id)
        else:
            # If no session_id specified, get the most recent channel session
            latest_channel_session = db.query(ChannelSession.channel_session_id).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.channel_name == channel_name
            ).order_by(desc(ChannelSession.join_time)).first()
            
            if latest_channel_session:
                query = query.filter(ChannelSession.channel_session_id == latest_channel_session.channel_session_id)
        
        sessions = query.order_by(desc(ChannelSession.join_time)).limit(1000).all()  # Limit to prevent huge responses
        
        session_responses = []
        for session in sessions:
            session_responses.append(ChannelSessionResponse(
                id=session.id,
                app_id=session.app_id,
                channel_name=session.channel_name,
                uid=session.uid,
                join_time=session.join_time,
                leave_time=session.leave_time,
                duration_seconds=session.duration_seconds,
                duration_minutes=session.duration_seconds / 60.0 if session.duration_seconds else None,
                product_id=session.product_id,
                platform=session.platform,
                reason=session.reason,
                client_type=session.client_type,
                communication_mode=session.communication_mode,
                is_host=session.is_host,
                role_switches=session.role_switches or 0,
                account=session.account
            ))
        
        # Calculate metrics based on filtered sessions (if session_id provided, use filtered sessions)
        # Otherwise use all sessions for the channel
        if session_id:
            # Use filtered sessions for metrics when viewing a specific session
            sessions_for_metrics = sessions
        else:
            # Get all sessions for this channel when no session_id specified
            all_sessions = db.query(ChannelSession).filter(
                ChannelSession.app_id == app_id,
                ChannelSession.channel_name == channel_name
            ).all()
            sessions_for_metrics = all_sessions
        
        # Calculate total metrics from filtered sessions
        total_minutes = sum(s.duration_seconds or 0 for s in sessions_for_metrics) / 60.0
        unique_users = len(set(s.uid for s in sessions_for_metrics))
        
        # Get role events for filtered sessions only (if session_id provided)
        if session_id:
            # Filter role events by the specific session_id
            all_role_events = db.query(RoleEvent).filter(
                RoleEvent.app_id == app_id,
                RoleEvent.channel_name == channel_name,
                RoleEvent.channel_session_id == session_id
            ).all()
        else:
            # Get all role events for this channel (across all sessions)
            all_role_events = db.query(RoleEvent).filter(
                RoleEvent.app_id == app_id,
                RoleEvent.channel_name == channel_name
            ).all()
        
        # Group sessions by channel_session_id for role calculation
        sessions_by_session_id = {}
        for s in sessions_for_metrics:
            if s.channel_session_id not in sessions_by_session_id:
                sessions_by_session_id[s.channel_session_id] = []
            sessions_by_session_id[s.channel_session_id].append(s)
        
        # Calculate role-split metrics using role_events if available
        host_minutes = 0.0
        audience_minutes = 0.0
        
        if all_role_events:
            # Calculate role minutes for each channel_session_id
            for ch_session_id, ch_sessions in sessions_by_session_id.items():
                ch_role_events = [re for re in all_role_events if re.channel_session_id == ch_session_id]
                if ch_role_events:
                    h_min, a_min = calculate_role_minutes_from_events(ch_sessions, ch_role_events, ch_session_id, db)
                    host_minutes += h_min
                    audience_minutes += a_min
                else:
                    # Fallback for sessions without role events
                    h_min = sum((s.duration_seconds or 0) for s in ch_sessions if s.is_host) / 60.0
                    a_min = sum((s.duration_seconds or 0) for s in ch_sessions if not s.is_host) / 60.0
                    host_minutes += h_min
                    audience_minutes += a_min
        else:
            # Fallback: use session-based calculation
            host_minutes = sum((s.duration_seconds or 0) for s in sessions_for_metrics if s.is_host) / 60.0
            audience_minutes = total_minutes - host_minutes
        
        unique_hosts = len(set(s.uid for s in sessions_for_metrics if s.is_host))
        unique_audiences = len(set(s.uid for s in sessions_for_metrics if not s.is_host))
        
        # Calculate channel metrics (wall time, user-minutes sum, utilization) from filtered sessions
        channel_duration_minutes = None
        user_minutes_sum = total_minutes  # Same as total_minutes (sum of all durations)
        utilization = None
        
        if sessions_for_metrics:
            # Find min join_time and max leave_time from filtered sessions
            join_times = [s.join_time for s in sessions_for_metrics if s.join_time]
            leave_times = [s.leave_time for s in sessions_for_metrics if s.leave_time and s.leave_time]
            
            if join_times and leave_times:
                min_join = min(join_times)
                max_leave = max(leave_times)
                channel_duration_seconds = (max_leave - min_join).total_seconds()
                channel_duration_minutes = channel_duration_seconds / 60.0
                
                # Calculate utilization: user-minutes / wall-minutes
                if channel_duration_minutes > 0:
                    utilization = user_minutes_sum / channel_duration_minutes
        
        return ChannelDetailResponse(
            channel_name=channel_name,
            total_minutes=total_minutes,
            unique_users=unique_users,
            sessions=session_responses,
            host_minutes=round(host_minutes, 2),
            audience_minutes=round(audience_minutes, 2),
            unique_hosts=unique_hosts,
            unique_audiences=unique_audiences,
            channel_duration_minutes=round(channel_duration_minutes, 2) if channel_duration_minutes else None,
            user_minutes_sum=round(user_minutes_sum, 2),
            utilization=round(utilization, 3) if utilization else None
        )
        
    except Exception as e:
        logger.error(f"Error getting channel details for {app_id}/{channel_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/user/{app_id}/{uid}")
async def get_user_metrics(app_id: str, uid: int, db: Session = Depends(get_db)):
    """Get metrics for a specific user"""
    try:
        # Get user sessions
        sessions = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.uid == uid
        ).order_by(desc(ChannelSession.join_time)).all()
        
        # Group by channel
        channel_stats = {}
        for session in sessions:
            channel = session.channel_name
            if channel not in channel_stats:
                channel_stats[channel] = {
                    'total_minutes': 0,
                    'session_count': 0
                }
            
            channel_stats[channel]['total_minutes'] += (session.duration_seconds or 0) / 60.0
            channel_stats[channel]['session_count'] += 1
        
        return {
            "uid": uid,
            "app_id": app_id,
            "channel_stats": channel_stats,
            "total_sessions": len(sessions)
        }
        
    except Exception as e:
        logger.error(f"Error getting user metrics for {app_id}/{uid}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/user/{app_id}/{uid}/detailed")
async def get_user_detailed_analytics(app_id: str, uid: int, db: Session = Depends(get_db)):
    """Get detailed user analytics including role switches, platform distribution, and quality insights"""
    try:
        # Get all sessions for this user
        sessions = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.uid == uid
        ).order_by(desc(ChannelSession.join_time)).all()
        
        if not sessions:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Calculate comprehensive metrics
        total_channels_joined = len(set(s.channel_name for s in sessions))
        total_active_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
        total_role_switches = sum(s.role_switches or 0 for s in sessions)
        
        # Platform distribution
        platform_counts = {}
        for session in sessions:
            if session.platform:
                platform_name = get_platform_name(session.platform)
                platform_counts[platform_name] = platform_counts.get(platform_name, 0) + 1
        
        # Quality metrics based on reason codes
        avg_session_length = total_active_minutes / len(sessions) if sessions else 0
        
        # Categorize exits by reason codes
        good_exits = len([s for s in sessions if s.reason == 1])  # Normal leave
        network_timeouts = len([s for s in sessions if s.reason == 2])  # Connection timeout
        permission_issues = len([s for s in sessions if s.reason == 3])  # Permissions issue
        server_issues = len([s for s in sessions if s.reason == 4])  # Server load adjustment
        device_switches = len([s for s in sessions if s.reason == 5])  # Device switch
        ip_switching = len([s for s in sessions if s.reason == 9])  # Multiple IP addresses
        network_issues = len([s for s in sessions if s.reason == 10])  # Network connection problems
        churn_events = len([s for s in sessions if s.reason == 999])  # Abnormal user
        other_issues = len([s for s in sessions if s.reason == 0])  # Other reasons
        
        failed_calls = len([s for s in sessions if (s.duration_seconds or 0) < 5])
        spike_detection_score = churn_events / len(sessions) if sessions else 0
        
        # Product breakdown
        product_breakdown = {}
        for session in sessions:
            product_name = get_product_name(session.product_id)
            minutes = (session.duration_seconds or 0) / 60.0
            product_breakdown[product_name] = product_breakdown.get(product_name, 0) + minutes
        
        # Channels list with details
        channels_list = []
        channel_stats = {}
        for session in sessions:
            channel = session.channel_name
            if channel not in channel_stats:
                channel_stats[channel] = {
                    'total_minutes': 0,
                    'session_count': 0,
                    'role_switches': 0,
                    'is_host': False,
                    'communication_mode': 0,
                    'last_activity': session.join_time
                }
            
            channel_stats[channel]['total_minutes'] += (session.duration_seconds or 0) / 60.0
            channel_stats[channel]['session_count'] += 1
            channel_stats[channel]['role_switches'] += session.role_switches or 0
            # Check if user was host/broadcaster
            # Host can be: broadcaster (communication_mode=0, is_host=True) OR communication host (communication_mode=1, is_host=True)
            if session.is_host:
                channel_stats[channel]['is_host'] = True
            # Use the communication_mode from the most recent session for this channel
            if session.join_time > channel_stats[channel]['last_activity']:
                channel_stats[channel]['communication_mode'] = session.communication_mode or 0
                channel_stats[channel]['last_activity'] = session.join_time
        
        for channel, stats in channel_stats.items():
            channels_list.append({
                'channel_name': channel,
                'total_minutes': round(stats['total_minutes'], 2),
                'session_count': stats['session_count'],
                'role_switches': stats['role_switches'],
                'is_host': stats['is_host'],
                'communication_mode': stats['communication_mode'],
                'last_activity': stats['last_activity'].isoformat()
            })
        
        # Quality insights based on reason codes
        quality_insights = []
        
        # High impact issues
        if churn_events > 0:
            quality_insights.append(f"🔴 User {uid} experienced {churn_events} abnormal leaves (reason=999) - frequent join/leave")
        if other_issues > 0:
            quality_insights.append(f"🔴 {other_issues} unknown issues (reason=0) - investigate further")
        
        # Medium impact issues
        if network_timeouts > 0:
            quality_insights.append(f"🟡 {network_timeouts} connection timeouts (reason=2) - network instability")
        if network_issues > 0:
            quality_insights.append(f"🟡 {network_issues} network connection problems (reason=10) - check connectivity")
        if ip_switching > 0:
            quality_insights.append(f"🟡 {ip_switching} IP switching events (reason=9) - VPN or multiple IPs detected")
        if server_issues > 0:
            quality_insights.append(f"🟡 {server_issues} server load adjustments (reason=4) - Agora server issues")
        
        # Low impact issues
        if permission_issues > 0:
            quality_insights.append(f"🟢 {permission_issues} permission issues (reason=3) - admin actions")
        if device_switches > 0:
            quality_insights.append(f"🟢 {device_switches} device switches (reason=5) - user behavior")
        
        # Good indicators
        if good_exits > 0:
            quality_insights.append(f"✅ {good_exits} normal exits (reason=1) - good user experience")
        
        # Other quality indicators
        if failed_calls > 0:
            quality_insights.append(f"📞 {failed_calls} failed calls detected (duration < 5s)")
        if total_role_switches > 5:
            quality_insights.append(f"🔄 High role switching activity: {total_role_switches} switches")
        if avg_session_length < 1:
            quality_insights.append(f"⏱️ Short average session length: {avg_session_length:.1f} minutes")
        
        # Collect SID from sessions - get the most recent non-null SID
        sid = None
        for session in sorted(sessions, key=lambda s: s.join_time, reverse=True):
            if session.sid:
                sid = session.sid
                break
        
        return UserDetailResponse(
            uid=uid,
            app_id=app_id,
            total_channels_joined=total_channels_joined,
            total_active_minutes=round(total_active_minutes, 2),
            total_role_switches=total_role_switches,
            platform_distribution=platform_counts,
            avg_session_length=round(avg_session_length, 2),
            spike_detection_score=round(spike_detection_score, 3),
            churn_events=churn_events,
            failed_calls=failed_calls,
            product_breakdown={k: round(v, 2) for k, v in product_breakdown.items()},
            channels_list=channels_list,
            quality_insights=quality_insights,
            sid=sid
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting detailed user analytics for {app_id}/{uid}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/channel/{app_id}/{channel_name}/role-analytics")
async def get_channel_role_analytics(app_id: str, channel_name: str, session_id: str = None, db: Session = Depends(get_db)):
    """Get role and product analytics for a specific channel session"""
    try:
        # Get sessions for this channel, optionally filtered by session_id
        query = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name
        )
        
        if session_id:
            # Filter by specific session if provided
            query = query.filter(ChannelSession.channel_session_id == session_id)
        
        sessions = query.all()
        
        if not sessions:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        # Get channel_session_id for filtering role events
        channel_session_id = sessions[0].channel_session_id if sessions else None
        
        # Get role events for this channel session if we have role events table
        role_events = []
        if channel_session_id:
            role_events = db.query(RoleEvent).filter(
                RoleEvent.app_id == app_id,
                RoleEvent.channel_name == channel_name,
                RoleEvent.channel_session_id == channel_session_id
            ).all()
        
        # Calculate role analytics
        total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
        
        # Use role_events to calculate role minutes if available, otherwise fall back to session-based calculation
        if role_events:
            host_minutes, audience_minutes = calculate_role_minutes_from_events(sessions, role_events, channel_session_id, db)
        else:
            # Fallback: use session-based calculation
            host_minutes = sum((s.duration_seconds or 0) for s in sessions if s.is_host) / 60.0
            audience_minutes = total_minutes - host_minutes
        
        total_role_switches = len(role_events) if role_events else sum(s.role_switches or 0 for s in sessions)
        
        # Calculate wall clock time (channel elapsed time) = max(leave) - min(join) for this channel_session_id
        wall_clock_minutes = None
        if sessions:
            join_times = [s.join_time for s in sessions if s.join_time]
            leave_times = [s.leave_time for s in sessions if s.leave_time and s.leave_time]
            
            if join_times and leave_times:
                min_join = min(join_times)
                max_leave = max(leave_times)
                wall_clock_seconds = (max_leave - min_join).total_seconds()
                wall_clock_minutes = wall_clock_seconds / 60.0
        
        # Product breakdown
        product_breakdown = {}
        for session in sessions:
            product_name = get_product_name(session.product_id)
            minutes = (session.duration_seconds or 0) / 60.0
            product_breakdown[product_name] = product_breakdown.get(product_name, 0) + minutes
        
        # Platform breakdown
        platform_breakdown = {}
        for session in sessions:
            if session.platform:
                platform_name = get_platform_name(session.platform)
                minutes = (session.duration_seconds or 0) / 60.0
                platform_breakdown[platform_name] = platform_breakdown.get(platform_name, 0) + minutes
        
        return RoleAnalyticsResponse(
            channel_name=channel_name,
            total_minutes=round(total_minutes, 2),
            host_minutes=round(host_minutes, 2),
            audience_minutes=round(audience_minutes, 2),
            role_switches=total_role_switches,
            wall_clock_minutes=round(wall_clock_minutes, 2) if wall_clock_minutes else None,
            product_breakdown={k: round(v, 2) for k, v in product_breakdown.items()},
            platform_breakdown={k: round(v, 2) for k, v in platform_breakdown.items()}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting role analytics for {app_id}/{channel_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/channel/{app_id}/{channel_name}/quality-metrics")
async def get_channel_quality_metrics(app_id: str, channel_name: str, session_id: str = None, db: Session = Depends(get_db)):
    """Get quality and health indicators for a specific channel session"""
    try:
        # Get sessions for this channel, optionally filtered by session_id
        query = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name
        )
        
        if session_id:
            # Filter by specific session if provided
            query = query.filter(ChannelSession.channel_session_id == session_id)
        
        sessions = query.all()
        
        if not sessions:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        # Calculate quality metrics
        session_lengths = [s.duration_seconds or 0 for s in sessions]
        avg_user_session_length = sum(session_lengths) / len(session_lengths) / 60.0 if session_lengths else 0
        
        # Session length histogram
        histogram = {
            "0-5s": len([s for s in session_lengths if s < 5]),
            "5-30s": len([s for s in session_lengths if 5 <= s < 30]),
            "30-60s": len([s for s in session_lengths if 30 <= s < 60]),
            "1-5min": len([s for s in session_lengths if 60 <= s < 300]),
            "5-15min": len([s for s in session_lengths if 300 <= s < 900]),
            "15min+": len([s for s in session_lengths if s >= 900])
        }
        
        # Quality indicators based on reason codes
        # Good reasons (normal exits)
        good_exits = len([s for s in sessions if s.reason == 1])  # Normal leave
        
        # Network/connection issues (moderate quality impact)
        network_timeouts = len([s for s in sessions if s.reason == 2])  # Connection timeout
        network_issues = len([s for s in sessions if s.reason == 10])  # Network connection problems
        ip_switching = len([s for s in sessions if s.reason == 9])  # Multiple IP addresses
        
        # Server issues (moderate quality impact)
        server_issues = len([s for s in sessions if s.reason == 4])  # Server load adjustment
        
        # Permission/control issues (low quality impact)
        permission_issues = len([s for s in sessions if s.reason == 3])  # Permissions issue
        device_switches = len([s for s in sessions if s.reason == 5])  # Device switch
        
        # Poor quality indicators
        churn_events = len([s for s in sessions if s.reason == 999])  # Abnormal user
        other_issues = len([s for s in sessions if s.reason == 0])  # Other reasons
        
        # Calculate total problematic exits
        problematic_exits = network_timeouts + network_issues + ip_switching + server_issues + churn_events + other_issues
        
        failed_calls = len([s for s in sessions if (s.duration_seconds or 0) < 5])
        test_channels = 1 if len(set(s.uid for s in sessions)) == 1 else 0
        
        # Calculate max concurrent users from join/leave pairs
        max_concurrent_users, peak_concurrent_time, concurrency_over_time = calculate_max_concurrency(sessions)
        
        # Calculate quality score (0-100) based on reason codes
        quality_score = 100
        
        # High impact: Abnormal users and other issues
        if churn_events > 0:
            quality_score -= min(churn_events * 15, 60)  # High penalty for abnormal users
        if other_issues > 0:
            quality_score -= min(other_issues * 10, 40)  # High penalty for unknown issues
        
        # Medium impact: Network and server issues
        network_issues_total = network_timeouts + network_issues + ip_switching
        if network_issues_total > 0:
            quality_score -= min(network_issues_total * 8, 35)  # Medium penalty for network issues
        if server_issues > 0:
            quality_score -= min(server_issues * 6, 25)  # Medium penalty for server issues
        
        # Low impact: Permission and device issues
        control_issues = permission_issues + device_switches
        if control_issues > 0:
            quality_score -= min(control_issues * 3, 15)  # Low penalty for control issues
        
        # Failed calls (short duration)
        if failed_calls > 0:
            quality_score -= min(failed_calls * 5, 30)
        
        # Session length impact
        if avg_user_session_length < 1:
            quality_score -= 20
        
        # Bonus for good exits (if most exits are normal)
        total_exits = len(sessions)
        if total_exits > 0 and good_exits / total_exits > 0.7:
            quality_score += 5  # Small bonus for mostly normal exits
        
        quality_score = max(0, min(100, quality_score))  # Clamp between 0-100
        
        # Generate insights based on reason codes
        insights = []
        
        # High impact issues
        if churn_events > 0:
            insights.append(f"🔴 {churn_events} abnormal user events (reason=999) - frequent join/leave")
        if other_issues > 0:
            insights.append(f"🔴 {other_issues} unknown issues (reason=0) - investigate further")
        
        # Medium impact issues
        if network_timeouts > 0:
            insights.append(f"🟡 {network_timeouts} connection timeouts (reason=2) - network instability")
        if network_issues > 0:
            insights.append(f"🟡 {network_issues} network connection problems (reason=10) - check connectivity")
        if ip_switching > 0:
            insights.append(f"🟡 {ip_switching} IP switching events (reason=9) - VPN or multiple IPs detected")
        if server_issues > 0:
            insights.append(f"🟡 {server_issues} server load adjustments (reason=4) - Agora server issues")
        
        # Low impact issues
        if permission_issues > 0:
            insights.append(f"🟢 {permission_issues} permission issues (reason=3) - admin actions")
        if device_switches > 0:
            insights.append(f"🟢 {device_switches} device switches (reason=5) - user behavior")
        
        # Good indicators
        if good_exits > 0:
            insights.append(f"✅ {good_exits} normal exits (reason=1) - good user experience")
        
        # Other quality indicators
        if failed_calls > 0:
            insights.append(f"📞 {failed_calls} failed calls (duration < 5s)")
        if test_channels:
            insights.append("🧪 Test channel detected (only 1 user)")
        if avg_user_session_length < 1:
            insights.append(f"⏱️ Short average session length: {avg_user_session_length:.1f} minutes")
        
        # Overall quality assessment
        if quality_score < 50:
            insights.append("🔴 Poor quality indicators detected")
        elif quality_score < 80:
            insights.append("🟡 Moderate quality indicators")
        else:
            insights.append("🟢 Good quality indicators")
        
        # Convert tuples to lists for JSON serialization
        concurrency_data = [[ts, count] for ts, count in concurrency_over_time] if concurrency_over_time else None
        
        return QualityMetricsResponse(
            channel_name=channel_name,
            avg_user_session_length=round(avg_user_session_length, 2),
            avg_join_to_media_time=0.0,  # Would need additional tracking
            max_concurrent_users=max_concurrent_users,
            churn_events=churn_events,
            failed_calls=failed_calls,
            test_channels=test_channels,
            session_length_histogram=histogram,
            peak_concurrent_time=peak_concurrent_time,
            concurrency_over_time=concurrency_data,
            quality_score=round(quality_score, 1),
            insights=insights
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting quality metrics for {app_id}/{channel_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/channel/{app_id}/{channel_name}/multi-user")
async def get_channel_multi_user_analytics(app_id: str, channel_name: str, session_id: str = None, db: Session = Depends(get_db)):
    """Get multi-user analytics for a specific channel session"""
    try:
        # Get sessions for this channel, optionally filtered by session_id
        query = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.channel_name == channel_name
        )
        
        if session_id:
            # Filter by specific session if provided
            query = query.filter(ChannelSession.channel_session_id == session_id)
        
        sessions = query.all()
        
        if not sessions:
            raise HTTPException(status_code=404, detail="Channel not found")
        
        # Group sessions by user
        user_sessions = {}
        for session in sessions:
            uid = session.uid
            if uid not in user_sessions:
                user_sessions[uid] = []
            user_sessions[uid].append(session)
        
        # Calculate analytics for each user
        user_analytics = []
        for uid, user_session_list in user_sessions.items():
            total_minutes = sum((s.duration_seconds or 0) for s in user_session_list) / 60.0
            total_channels = len(set(s.channel_name for s in user_session_list))
            total_role_switches = sum(s.role_switches or 0 for s in user_session_list)
            
            # Platform distribution
            platform_dist = {}
            for session in user_session_list:
                platform = session.platform or 'Unknown'
                platform_dist[platform] = platform_dist.get(platform, 0) + 1
            
            # Failed calls (sessions < 5 seconds)
            failed_calls = len([s for s in user_session_list if (s.duration_seconds or 0) < 5])
            
            # Comprehensive reason code analysis per user
            good_exits = len([s for s in user_session_list if s.reason == 1])  # Normal leave
            network_timeouts = len([s for s in user_session_list if s.reason == 2])  # Connection timeout
            permission_issues = len([s for s in user_session_list if s.reason == 3])  # Permissions issue
            server_issues = len([s for s in user_session_list if s.reason == 4])  # Server load adjustment
            device_switches = len([s for s in user_session_list if s.reason == 5])  # Device switch
            ip_switching = len([s for s in user_session_list if s.reason == 9])  # Multiple IP addresses
            network_issues = len([s for s in user_session_list if s.reason == 10])  # Network connection problems
            churn_events = len([s for s in user_session_list if s.reason == 999])  # Abnormal user
            other_issues = len([s for s in user_session_list if s.reason == 0])  # Other reasons
            
            # Analyze reconnection patterns and burst behavior
            reconnection_analysis = analyze_user_reconnection_patterns(user_session_list, uid)
            
            # Calculate user quality score
            user_quality_score = 100
            
            # High impact issues
            if churn_events > 0:
                user_quality_score -= min(churn_events * 15, 60)
            if other_issues > 0:
                user_quality_score -= min(other_issues * 10, 40)
            
            # Medium impact issues
            network_issues_total = network_timeouts + network_issues + ip_switching
            if network_issues_total > 0:
                user_quality_score -= min(network_issues_total * 8, 35)
            if server_issues > 0:
                user_quality_score -= min(server_issues * 6, 25)
            
            # Low impact issues
            control_issues = permission_issues + device_switches
            if control_issues > 0:
                user_quality_score -= min(control_issues * 3, 15)
            
            # Failed calls
            if failed_calls > 0:
                user_quality_score -= min(failed_calls * 5, 30)
            
            # Reconnection pattern impact
            if reconnection_analysis['reconnection_pattern'] == 'unstable':
                user_quality_score -= 25  # High penalty for unstable connections
            elif reconnection_analysis['reconnection_pattern'] == 'moderate':
                user_quality_score -= 15  # Medium penalty for moderate reconnections
            elif reconnection_analysis['rapid_reconnections'] > 0:
                user_quality_score -= 10  # Light penalty for any rapid reconnections
            
            # Burst behavior impact
            if reconnection_analysis['burst_sessions'] > 0:
                user_quality_score -= min(reconnection_analysis['burst_sessions'] * 5, 20)
            
            # Session length impact
            avg_session_length = total_minutes / len(user_session_list) if user_session_list else 0
            if avg_session_length < 1:
                user_quality_score -= 20
            
            # Bonus for good exits
            total_exits = len(user_session_list)
            if total_exits > 0 and good_exits / total_exits > 0.7:
                user_quality_score += 5
            
            user_quality_score = max(0, min(100, user_quality_score))
            
            user_analytics.append({
                'uid': uid,
                'total_channels_joined': total_channels,
                'total_active_minutes': round(total_minutes, 2),
                'total_role_switches': total_role_switches,
                'platform_distribution': platform_dist,
                'failed_calls': failed_calls,
                'churn_events': churn_events,
                'quality_score': round(user_quality_score, 1),
                'reason_breakdown': {
                    'good_exits': good_exits,
                    'network_timeouts': network_timeouts,
                    'permission_issues': permission_issues,
                    'server_issues': server_issues,
                    'device_switches': device_switches,
                    'ip_switching': ip_switching,
                    'network_issues': network_issues,
                    'other_issues': other_issues
                },
                'reconnection_analysis': reconnection_analysis
            })
        
        # Sort by total active minutes (descending)
        user_analytics.sort(key=lambda x: x['total_active_minutes'], reverse=True)
        
        return {
            'channel_name': channel_name,
            'users': user_analytics,  # Return all users, not just top 4
            'total_users': len(user_analytics)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting multi-user analytics for {app_id}/{channel_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

def get_platform_name(platform_id: int) -> str:
    """Convert platform ID to readable name"""
    from mappings import PLATFORM_MAPPING
    return PLATFORM_MAPPING.get(platform_id, f"Platform {platform_id}")

def get_product_name(product_id: int) -> str:
    """Convert product ID to readable name"""
    product_map = {
        1: "RTC",
        2: "Cloud Recording",
        3: "Media Push",
        4: "Media Pull",
        5: "Conversational AI"
    }
    return product_map.get(product_id, f"Product {product_id}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

@app.get("/debug/cache")
async def debug_cache():
    """Debug endpoint to check webhook processor cache status"""
    try:
        # Get cache stats from the webhook processor
        # Note: This assumes we have access to the processor instance
        # In a real implementation, you might want to store this in a global variable
        # or use a different approach to access the processor
        return {
            "message": "Cache debug endpoint - check server logs for cache stats",
            "note": "Cache statistics are logged when webhooks are processed"
        }
    except Exception as e:
        logger.error(f"Error getting cache stats: {e}")
        return {"error": "Failed to get cache stats"}

@app.post("/api/export/{app_id}")
@rate_limit(max_requests=10, window_seconds=60)  # 10 exports per minute
async def export_data(app_id: str, request_body: ExportRequest, http_request: Request, db: Session = Depends(get_db)):
    """Export data for a specific App ID with optional filters"""
    try:
        # Set the app_id from the URL path
        request_body.app_id = app_id
        
        # Parse string dates to datetime objects if they're strings
        if isinstance(request_body.start_date, str):
            request_body.start_date = datetime.fromisoformat(request_body.start_date.replace('Z', '+00:00'))
        if isinstance(request_body.end_date, str):
            request_body.end_date = datetime.fromisoformat(request_body.end_date.replace('Z', '+00:00'))
        
        # Validate export request for security
        validation_result = ExportSecurity.validate_export_request(request_body.dict())
        if not validation_result['valid']:
            raise HTTPException(status_code=400, detail=f"Export validation failed: {', '.join(validation_result['errors'])}")
        
        # Use sanitized data
        request_body = ExportRequest(**validation_result['sanitized_data'])
        
        # Validate request
        if not request_body.start_date and not request_body.end_date:
            # Default to last 7 days if no date range provided
            request_body.start_date = datetime.utcnow() - timedelta(days=7)
            request_body.end_date = datetime.utcnow()
        
        # Create export service
        export_service = ExportService(db)
        
        # Generate export
        export_result = export_service.export_data(request_body)
        
        # Log completion - handle both regular and chunked export formats
        total_records = export_result.get('export_info', {}).get('total_records', 0) or export_result.get('total_records', 0)
        logger.info(f"Export completed for app_id {app_id}: {total_records} records")
        
        # Handle CSV export (zip file) - check for both zip_file (regular) and zip_content (chunked)
        if request_body.format.lower() == "csv":
            if "zip_file" in export_result:
                zip_data = export_result["zip_file"]
                filename = f"agora_export_{app_id}_{request_body.start_date.strftime('%Y%m%d')}_to_{request_body.end_date.strftime('%Y%m%d')}.zip"
                total_records = export_result.get('export_info', {}).get('total_records', 0)
                return Response(
                    content=zip_data,
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f"attachment; filename={filename}",
                        "X-Total-Records": str(total_records)
                    }
                )
            elif "zip_content" in export_result:
                # Handle chunked export
                zip_data = export_result["zip_content"]
                filename = export_result.get("filename", f"agora_export_{app_id}_{request_body.start_date.strftime('%Y%m%d')}_to_{request_body.end_date.strftime('%Y%m%d')}.zip")
                total_records = export_result.get('total_records', 0)
                return Response(
                    content=zip_data,
                    media_type="application/zip",
                    headers={
                        "Content-Disposition": f"attachment; filename={filename}",
                        "X-Total-Records": str(total_records)
                    }
                )
        
        # Handle JSON export
        return export_result
        
    except ValueError as e:
        logger.error(f"Export validation error for app_id {app_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting data for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/export/{app_id}/channels")
async def get_export_channels(app_id: str, db: Session = Depends(get_db)):
    """Get list of channels available for export for a specific App ID"""
    try:
        # Get unique channels for the app
        channels = db.query(ChannelSession.channel_name).filter(
            ChannelSession.app_id == app_id
        ).distinct().all()
        
        channel_list = [{"channel_name": channel[0]} for channel in channels]
        
        return {
            "app_id": app_id,
            "channels": channel_list,
            "total_channels": len(channel_list)
        }
        
    except Exception as e:
        logger.error(f"Error getting export channels for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/export/{app_id}/date-range")
async def get_export_date_range(app_id: str, db: Session = Depends(get_db)):
    """Get available date range for export for a specific App ID"""
    try:
        # Get date range from webhook events
        date_range = db.query(
            func.min(WebhookEvent.received_at).label('earliest'),
            func.max(WebhookEvent.received_at).label('latest')
        ).filter(WebhookEvent.app_id == app_id).first()
        
        if not date_range or not date_range.earliest:
            return {
                "app_id": app_id,
                "earliest_date": None,
                "latest_date": None,
                "message": "No data available for export"
            }
        
        return {
            "app_id": app_id,
            "earliest_date": date_range.earliest.isoformat(),
            "latest_date": date_range.latest.isoformat(),
            "total_days": (date_range.latest - date_range.earliest).days + 1
        }
        
    except Exception as e:
        logger.error(f"Error getting export date range for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/export/{app_id}/validate")
async def validate_export_request(app_id: str, request_body: ExportRequest, db: Session = Depends(get_db)):
    """Validate export request and return limits information"""
    try:
        # Set the app_id from the URL path
        request_body.app_id = app_id
        
        # Parse string dates to datetime objects if they're strings
        if isinstance(request_body.start_date, str):
            request_body.start_date = datetime.fromisoformat(request_body.start_date.replace('Z', '+00:00'))
        if isinstance(request_body.end_date, str):
            request_body.end_date = datetime.fromisoformat(request_body.end_date.replace('Z', '+00:00'))
        
        # Create export service
        export_service = ExportService(db)
        
        # Validate export limits
        validation_result = export_service.validate_export_limits(request_body)
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Error validating export request for {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/export/{app_id}/share")
async def create_public_share(app_id: str, request_body: ExportRequest, db: Session = Depends(get_db)):
    """Create a public share URL for filtered data"""
    try:
        # Set the app_id from the URL path
        request.app_id = app_id
        
        # Parse string dates to datetime objects if they're strings
        if isinstance(request.start_date, str):
            request.start_date = datetime.fromisoformat(request.start_date.replace('Z', '+00:00'))
        if isinstance(request.end_date, str):
            request.end_date = datetime.fromisoformat(request.end_date.replace('Z', '+00:00'))
        
        # Create export service
        export_service = ExportService(db)
        
        # Generate a share token (in production, this would be stored in database)
        import secrets
        share_token = secrets.token_urlsafe(32)
        
        # Create public share URL
        share_url = export_service.create_public_share_url(request, share_token)
        
        return {
            "share_url": share_url,
            "token": share_token,
            "expires_at": (datetime.utcnow() + timedelta(days=7)).isoformat(),
            "note": "This is a read-only view of the filtered data"
        }
        
    except Exception as e:
        logger.error(f"Error creating public share for {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/export/public/{token}")
async def get_public_share(token: str, db: Session = Depends(get_db)):
    """Get public share data (read-only)"""
    try:
        # In production, you would validate the token and get the original request
        # For now, we'll return a placeholder response
        return {
            "message": "Public share endpoint - token validation and data retrieval would be implemented here",
            "token": token,
            "note": "This endpoint would return the filtered data based on the original export request"
        }
        
    except Exception as e:
        logger.error(f"Error getting public share {token}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/analytics/minutes/{app_id}", response_model=MinutesAnalyticsResponse)
async def get_minutes_analytics(app_id: str, request: Request, db: Session = Depends(get_db)):
    """Get total minutes analytics per day or per month with filters"""
    try:
        # Get raw request body to handle None values in client_types
        body = await request.json()
        
        # Parse client_types specially to handle None values
        if 'client_types' in body and body['client_types']:
            # Convert None/null values in the list
            client_types_processed = []
            for ct in body['client_types']:
                if ct is None:
                    client_types_processed.append(None)
                elif isinstance(ct, (int, str)):
                    try:
                        client_types_processed.append(int(ct))
                    except (ValueError, TypeError):
                        client_types_processed.append(None)
                else:
                    client_types_processed.append(ct)
            body['client_types'] = client_types_processed
        
        # Now parse the full request body
        request_body = MinutesAnalyticsRequest(**body)
        
        # Set app_id from URL path
        request_body.app_id = app_id
        
        # Default to last 30 days if no date range provided
        if not request_body.start_date:
            request_body.start_date = datetime.utcnow() - timedelta(days=30)
        if not request_body.end_date:
            request_body.end_date = datetime.utcnow()
        
        # Normalize dates to full months if period is "month"
        if request_body.period == "month":
            from calendar import monthrange
            # Normalize start_date to first day of the month
            start_date_normalized = request_body.start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Normalize end_date to last day of the month
            last_day = monthrange(request_body.end_date.year, request_body.end_date.month)[1]
            end_date_normalized = request_body.end_date.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
            
            # Use normalized dates for query
            query_start_date = start_date_normalized
            query_end_date = end_date_normalized
        else:
            # Use dates as-is for daily period
            query_start_date = request_body.start_date
            query_end_date = request_body.end_date
        
        # Build query - include sessions that overlap the date range
        # A session overlaps if: join_time <= query_end_date AND leave_time >= query_start_date
        # For sessions without leave_time (incomplete), include if they started before or during query range
        # (they overlap the query range since they're still active)
        query = db.query(ChannelSession).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.duration_seconds.isnot(None),
            or_(
                # Session overlaps the date range (has leave_time and overlaps)
                and_(
                    ChannelSession.join_time.isnot(None),
                    ChannelSession.leave_time.isnot(None),
                    ChannelSession.join_time <= query_end_date,
                    ChannelSession.leave_time >= query_start_date
                ),
                # Incomplete session overlaps query range (started before or during query range, still active)
                and_(
                    ChannelSession.join_time.isnot(None),
                    ChannelSession.leave_time.is_(None),
                    ChannelSession.join_time <= query_end_date  # Started before or during query range
                )
            )
        )
        
        # Apply client type filter first to determine if we need to adjust platform filter
        # Handle None/null values specially - filter for NULL client_type (only for Linux platform)
        needs_linux_for_none = False
        if request_body.client_types and len(request_body.client_types) > 0:
            # Separate None/null values from regular client types
            none_values = [ct for ct in request_body.client_types if ct is None]
            needs_linux_for_none = len(none_values) > 0
        
        # Apply platform filter (multi-select)
        # If None client type is selected, ensure Linux (platform 6) is included
        platform_filter_list = None
        if request_body.platforms and len(request_body.platforms) > 0:
            platform_filter_list = request_body.platforms.copy()
            if needs_linux_for_none and 6 not in platform_filter_list:
                # Add Linux (platform 6) if None client type is selected but Linux wasn't explicitly selected
                platform_filter_list.append(6)
        elif needs_linux_for_none:
            # If no platforms selected but None client type is selected, only show Linux
            platform_filter_list = [6]
        
        if platform_filter_list:
            query = query.filter(ChannelSession.platform.in_(platform_filter_list))
        
        # Apply client type filter (multi-select)
        if request_body.client_types and len(request_body.client_types) > 0:
            # Separate None/null values from regular client types
            none_values = [ct for ct in request_body.client_types if ct is None]
            regular_values = [ct for ct in request_body.client_types if ct is not None]
            
            logger.info(f"Client type filter: none_values={none_values}, regular_values={regular_values}, "
                       f"platform_filter_list={platform_filter_list}")
            
            filter_conditions = []
            if none_values:
                # Add condition for NULL client_type - only for Linux (platform 6)
                filter_conditions.append(
                    and_(
                        ChannelSession.client_type.is_(None),
                        ChannelSession.platform == 6  # Only Linux
                    )
                )
            if regular_values:
                # Add condition for specific client types
                filter_conditions.append(ChannelSession.client_type.in_(regular_values))
            
            if filter_conditions:
                query = query.filter(or_(*filter_conditions))
        
        # Apply role filter (multi-select)
        if request_body.role and len(request_body.role) > 0:
            # If roles are specified, filter to only include those roles
            role_filters = []
            if "host" in request_body.role:
                role_filters.append(ChannelSession.is_host == True)
            if "audience" in request_body.role:
                role_filters.append(ChannelSession.is_host == False)
            if role_filters:
                query = query.filter(or_(*role_filters))
        
        sessions = query.all()
        
        # Debug logging for None client type sessions
        none_sessions = [s for s in sessions if s.client_type is None]
        logger.info(f"Minutes analytics query: Found {len(sessions)} total sessions, {len(none_sessions)} with None client_type")
        if none_sessions:
            sample_dates = {}
            for s in none_sessions[:50]:  # Increased sample size
                date_key = s.join_time.date().strftime("%Y-%m-%d")
                if date_key not in sample_dates:
                    sample_dates[date_key] = {'host': 0, 'audience': 0, 'total_minutes': 0.0, 'count': 0}
                sample_dates[date_key]['count'] += 1
                sample_dates[date_key]['total_minutes'] += (s.duration_seconds or 0) / 60.0
                if s.is_host:
                    sample_dates[date_key]['host'] += 1
                else:
                    sample_dates[date_key]['audience'] += 1
            logger.info(f"None client_type sessions breakdown by date: {sample_dates}")
        
        # Aggregate by period and breakdown dimension
        period_format = "%Y-%m-%d" if request_body.period == "day" else "%Y-%m"
        
        # Group data by series key based on breakdown_by option
        # If breakdown_by == "role": group by (role, client_type)
        # If breakdown_by == "platform": group by (platform, client_type)
        series_data = {}
        
        # Get all unique combinations
        from mappings import get_client_type_name, get_platform_name
        
        for session in sessions:
            # Get client type
            client_type = session.client_type
            platform = session.platform
            
            # Determine series key based on breakdown_by
            if request_body.breakdown_by == "platform":
                # Group by platform + client_type
                series_key = (platform, client_type)
            else:
                # Default: group by role + client_type
                # This includes None/empty client_type as a separate category
                role = "host" if session.is_host else "audience"
                series_key = (role, client_type)
            
            # Initialize series if needed
            if series_key not in series_data:
                series_data[series_key] = {}
            
            # Split session duration across days if it spans multiple days
            if session.join_time and session.leave_time and session.duration_seconds:
                join_date = session.join_time.date()
                leave_date = session.leave_time.date()
                
                # Only count days that fall within the query date range
                query_start_date_only = query_start_date.date()
                query_end_date_only = query_end_date.date()
                
                if join_date == leave_date:
                    # Session is entirely within one day
                    # Only count if this day overlaps the query range
                    if query_start_date_only <= join_date <= query_end_date_only:
                        # Check if session actually overlaps query time range
                        # For single-day sessions, check if session overlaps query datetime range
                        session_start = session.join_time
                        session_end = session.leave_time
                        
                        # Normalize timezones for comparison
                        # If query dates are naive, make them aware; if session times are naive, make them aware
                        if query_start_date.tzinfo is None and session_start.tzinfo is not None:
                            # Query dates are naive, session is aware - make query dates aware (UTC)
                            from datetime import timezone
                            query_start_normalized = query_start_date.replace(tzinfo=timezone.utc)
                            query_end_normalized = query_end_date.replace(tzinfo=timezone.utc)
                        elif query_start_date.tzinfo is not None and session_start.tzinfo is None:
                            # Query dates are aware, session is naive - make session aware (UTC)
                            from datetime import timezone
                            session_start = session_start.replace(tzinfo=timezone.utc)
                            session_end = session_end.replace(tzinfo=timezone.utc)
                            query_start_normalized = query_start_date
                            query_end_normalized = query_end_date
                        else:
                            # Both are same type (both naive or both aware)
                            query_start_normalized = query_start_date
                            query_end_normalized = query_end_date
                        
                        # Session overlaps if it starts before query ends and ends after query starts
                        if session_start <= query_end_normalized and session_end >= query_start_normalized:
                            date_key = join_date.strftime(period_format)
                            if date_key not in series_data[series_key]:
                                series_data[series_key][date_key] = 0.0
                            series_data[series_key][date_key] += (session.duration_seconds or 0) / 60.0
                else:
                    # Session spans multiple days - split duration proportionally
                    join_datetime = session.join_time
                    leave_datetime = session.leave_time
                    total_duration_seconds = session.duration_seconds
                    
                    # Calculate minutes for each day, but only count days within query range
                    current_date = join_date
                    while current_date <= leave_date:
                        # Skip days outside the query range
                        if current_date < query_start_date_only or current_date > query_end_date_only:
                            current_date += timedelta(days=1)
                            continue
                        
                        # Calculate the start and end of this day (00:00:00 to 23:59:59.999999)
                        from datetime import time as dt_time
                        day_start = datetime.combine(current_date, dt_time(0, 0, 0))
                        day_end = datetime.combine(current_date, dt_time(23, 59, 59, 999999))
                        
                        # Normalize timezones - ensure day_start/day_end match join_datetime timezone
                        if join_datetime.tzinfo:
                            day_start = day_start.replace(tzinfo=join_datetime.tzinfo)
                            day_end = day_end.replace(tzinfo=join_datetime.tzinfo)
                        elif day_start.tzinfo is None:
                            # Both are naive, ensure they stay naive
                            pass
                        
                        # Determine the actual session time range for this day
                        # Use the intersection of session time and day boundaries
                        # Don't clamp to query boundaries here - we've already filtered days
                        session_start = max(join_datetime, day_start)
                        session_end = min(leave_datetime, day_end)
                        
                        # Calculate duration in this day
                        if session_start < session_end:
                            day_duration_seconds = (session_end - session_start).total_seconds()
                            day_minutes = day_duration_seconds / 60.0
                            
                            date_key = current_date.strftime(period_format)
                            if date_key not in series_data[series_key]:
                                series_data[series_key][date_key] = 0.0
                            series_data[series_key][date_key] += day_minutes
                        
                        # Move to next day
                        current_date += timedelta(days=1)
            else:
                # Handle incomplete sessions (no leave_time) - split across days like multi-day sessions
                if session.join_time:
                    join_date = session.join_time.date()
                    join_datetime = session.join_time
                    
                    # Only count days that fall within the query date range
                    query_start_date_only = query_start_date.date()
                    query_end_date_only = query_end_date.date()
                    
                    # For incomplete sessions, use query_end_date as the effective end time
                    # (session is still active, so count up to end of query range or end of day)
                    effective_end_datetime = query_end_date
                    if join_datetime.tzinfo and query_end_date.tzinfo is None:
                        from datetime import timezone
                        effective_end_datetime = query_end_date.replace(tzinfo=timezone.utc)
                    elif join_datetime.tzinfo is None and query_end_date.tzinfo:
                        effective_end_datetime = query_end_date.replace(tzinfo=None)
                    
                    # Calculate minutes for each day from join_date to query_end_date
                    current_date = join_date
                    while current_date <= query_end_date_only:
                        # Skip days outside the query range
                        if current_date < query_start_date_only or current_date > query_end_date_only:
                            current_date += timedelta(days=1)
                            continue
                        
                        # Calculate the start and end of this day
                        from datetime import time as dt_time
                        day_start = datetime.combine(current_date, dt_time(0, 0, 0))
                        day_end = datetime.combine(current_date, dt_time(23, 59, 59, 999999))
                        
                        # Normalize timezones
                        if join_datetime.tzinfo:
                            day_start = day_start.replace(tzinfo=join_datetime.tzinfo)
                            day_end = day_end.replace(tzinfo=join_datetime.tzinfo)
                        
                        # Determine the actual session time range for this day
                        # For incomplete sessions, use join_time to min(day_end, effective_end_datetime)
                        session_start = max(join_datetime, day_start)
                        session_end = min(effective_end_datetime, day_end)
                        
                        # Calculate duration in this day
                        if session_start < session_end:
                            day_duration_seconds = (session_end - session_start).total_seconds()
                            day_minutes = day_duration_seconds / 60.0
                            
                            date_key = current_date.strftime(period_format)
                            if date_key not in series_data[series_key]:
                                series_data[series_key][date_key] = 0.0
                            series_data[series_key][date_key] += day_minutes
                        
                        # Move to next day
                        current_date += timedelta(days=1)
                else:
                    # No join_time either - skip this session
                    pass
        
        # Generate all date keys for the period
        all_date_keys = []
        if request_body.period == "day":
            current_date = request_body.start_date.date()
            end_date = request_body.end_date.date()
            while current_date <= end_date:
                date_key = current_date.strftime(period_format)
                display_date = current_date.strftime("%b %d, %Y")
                all_date_keys.append({"date": date_key, "display_date": display_date})
                current_date += timedelta(days=1)
        else:
            # For monthly, iterate through all months from normalized start to normalized end
            current_date = query_start_date.date().replace(day=1)
            end_date_obj = query_end_date.date()
            
            while current_date <= end_date_obj:
                month_key = current_date.strftime(period_format)
                if month_key not in [d["date"] for d in all_date_keys]:
                    month_name = current_date.strftime("%B %Y")
                    all_date_keys.append({"date": month_key, "display_date": month_name})
                
                # Move to next month
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1, day=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1, day=1)
        
        # Sort date keys
        all_date_keys.sort(key=lambda x: x["date"])
        
        # Build series with data points
        series_list = []
        color_palette = [
            '#667eea', '#764ba2', '#f093fb', '#4facfe', '#00f2fe',
            '#43e97b', '#fa709a', '#fee140', '#fa709a', '#30cfd0',
            '#a8edea', '#fed6e3', '#ff9a9e', '#fecfef', '#fecfef'
        ]
        
        # Sort series keys, handling None values
        def sort_key(item):
            key = item[0]
            if request_body.breakdown_by == "platform":
                platform, client_type = key
                return (platform or 0, client_type if client_type is not None else -1)  # Use -1 for None to sort separately from 0
            else:
                role, client_type = key
                return (role, client_type if client_type is not None else -1)  # Use -1 for None to sort separately from 0
        
        sorted_series = sorted(series_data.items(), key=sort_key)
        
        series_index = 0
        for series_key, date_data in sorted_series:
            # Build label based on breakdown_by
            if request_body.breakdown_by == "platform":
                platform, client_type = series_key
                platform_name = get_platform_name(platform) if platform else None
                # Check if client_type is None (not just falsy - 0 is valid!)
                if client_type is not None:
                    client_type_name = get_client_type_name(client_type)
                    if platform_name and client_type_name:
                        label = f"{platform_name} - {client_type_name}"
                    elif platform_name:
                        label = platform_name
                    elif client_type_name:
                        label = f"Unknown Platform - {client_type_name}"
                    else:
                        label = "Unknown"
                else:
                    # Client type is None
                    if platform_name:
                        label = f"{platform_name} - None"
                    else:
                        label = "Unknown Platform - None"
            else:
                # Default: role + client_type
                role, client_type = series_key
                role_label = role.capitalize()
                # Check if client_type is None (not just falsy - 0 is valid!)
                if client_type is not None:
                    client_type_name = get_client_type_name(client_type)
                    label = f"{role_label} - {client_type_name}"
                else:
                    label = f"{role_label} - None"
            
            # Build data points for this series
            data_points = []
            for date_info in all_date_keys:
                date_key = date_info["date"]
                minutes = round(date_data.get(date_key, 0.0), 2)
                data_points.append(minutes)
            
            # Calculate total for this series
            series_total = sum(data_points)
            
            # Debug logging for None client type series
            if request_body.breakdown_by == "platform":
                platform, client_type = series_key
                if client_type is None:
                    logger.info(f"Series with None client_type (platform breakdown): key={series_key}, label={label}, total={series_total}, "
                              f"sample_dates={[(all_date_keys[i]['date'], dp) for i, dp in enumerate(data_points) if dp > 0][:5]}")
            else:
                role, client_type = series_key
                if client_type is None:
                    logger.info(f"Series with None client_type (role breakdown): key={series_key}, label={label}, total={series_total}, "
                              f"sample_dates={[(all_date_keys[i]['date'], dp) for i, dp in enumerate(data_points) if dp > 0][:5]}")
            
            # Only include series with data
            if series_total > 0:
                series_info = {
                    "label": label,
                    "data": data_points,
                    "total_minutes": round(series_total, 2),
                    "color": color_palette[series_index % len(color_palette)]
                }
                
                # Add dimension-specific fields
                if request_body.breakdown_by == "platform":
                    platform, client_type = series_key
                    series_info["platform"] = platform
                    series_info["platform_name"] = get_platform_name(platform) if platform else None
                    series_info["client_type"] = client_type
                    series_info["client_type_name"] = get_client_type_name(client_type) if client_type is not None else None
                else:
                    role, client_type = series_key
                    series_info["role"] = role
                    series_info["client_type"] = client_type
                    series_info["client_type_name"] = get_client_type_name(client_type) if client_type is not None else None
                
                series_list.append(series_info)
                series_index += 1
        
        # Calculate total minutes across all series
        total_minutes = sum(s["total_minutes"] for s in series_list)
        
        # Build data_points for backward compatibility (total across all series)
        data_points = []
        for date_info in all_date_keys:
            date_key = date_info["date"]
            total_for_date = sum(
                series_data.get(key, {}).get(date_key, 0.0)
                for key in series_data.keys()
            )
            data_points.append({
                "date": date_key,
                "minutes": round(total_for_date, 2),
                "display_date": date_info["display_date"]
            })
        
        # Build filters dict
        filters = {
            "platforms": request_body.platforms,
            "client_types": request_body.client_types,
            "role": request_body.role,
            "breakdown_by": request_body.breakdown_by
        }
        
        return MinutesAnalyticsResponse(
            app_id=app_id,
            start_date=request_body.start_date,
            end_date=request_body.end_date,
            period=request_body.period,
            total_minutes=round(total_minutes, 2),
            data_points=data_points,
            filters=filters,
            series=series_list
        )
        
    except Exception as e:
        logger.error(f"Error getting minutes analytics for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/mappings/platforms")
async def get_platform_mapping():
    """Get platform ID to name mapping"""
    from mappings import PLATFORM_MAPPING
    return {"platform_mapping": PLATFORM_MAPPING}

@app.get("/api/analytics/platforms/{app_id}")
async def get_platforms_for_app(app_id: str, db: Session = Depends(get_db)):
    """Get available platforms for an app"""
    try:
        platforms = db.query(ChannelSession.platform).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.platform.isnot(None)
        ).distinct().all()
        
        platform_list = [p[0] for p in platforms if p[0] is not None]
        platform_list.sort()
        
        # Get names from mappings
        from mappings import PLATFORM_MAPPING
        platforms_with_names = [
            {
                "id": pid,
                "name": PLATFORM_MAPPING.get(pid, f"Platform {pid}")
            }
            for pid in platform_list
        ]
        
        return {
            "app_id": app_id,
            "platforms": platforms_with_names
        }
        
    except Exception as e:
        logger.error(f"Error getting platforms for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/api/analytics/client-types/{app_id}")
async def get_client_types_for_app(app_id: str, platform_id: int = None, db: Session = Depends(get_db)):
    """Get available client types for an app, optionally filtered by platform"""
    try:
        query = db.query(ChannelSession.client_type).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.client_type.isnot(None)
        )
        
        if platform_id:
            query = query.filter(ChannelSession.platform == platform_id)
        
        client_types = query.distinct().all()
        client_type_list = [ct[0] for ct in client_types if ct[0] is not None]
        client_type_list.sort()
        
        # Get names from mappings
        from mappings import get_client_type_name
        client_types_with_names = [
            {
                "id": ct,
                "name": get_client_type_name(ct)
            }
            for ct in client_type_list
        ]
        
        return {
            "app_id": app_id,
            "platform_id": platform_id,
            "client_types": client_types_with_names
        }
        
    except Exception as e:
        logger.error(f"Error getting client types for app_id {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


if __name__ == "__main__":
    # Create templates directory if it doesn't exist
    import os
    os.makedirs("templates", exist_ok=True)
    
    # Start HTTP server (no SSL for now)
    logger.info(f"Starting server on {Config.HOST}:{Config.PORT}")
    
    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=False
    )
