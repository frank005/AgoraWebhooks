import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import uvicorn

from config import Config
from database import get_db, create_tables, ChannelSession, ChannelMetrics, UserMetrics, WebhookEvent
from models import WebhookRequest, ChannelSessionResponse, ChannelMetricsResponse, UserMetricsResponse, ChannelListResponse, ChannelDetailResponse, ExportRequest, ExportResponse, UserDetailResponse, RoleAnalyticsResponse, QualityMetricsResponse
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

# Initialize webhook processor
webhook_processor = WebhookProcessor()

# Webhook signature verification has been removed for simplified processing

# Create FastAPI app
app = FastAPI(title="Agora Webhooks Server", version="1.0.0")

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
        async def wrapper(*args, **kwargs):
            # Get client IP
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            if not request:
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
@rate_limit(max_requests=1000, window_seconds=60)  # 1000 requests per minute for webhooks
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
                client_type=session.client_type
            ))
        
        # Calculate total metrics
        total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
        unique_users = len(set(s.uid for s in sessions))
        
        return ChannelDetailResponse(
            channel_name=channel_name,
            total_minutes=total_minutes,
            unique_users=unique_users,
            sessions=session_responses
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
        
        # Quality metrics
        avg_session_length = total_active_minutes / len(sessions) if sessions else 0
        churn_events = len([s for s in sessions if s.reason == 999])
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
                    'last_activity': session.join_time
                }
            
            channel_stats[channel]['total_minutes'] += (session.duration_seconds or 0) / 60.0
            channel_stats[channel]['session_count'] += 1
            channel_stats[channel]['role_switches'] += session.role_switches or 0
            # Check if user was host/broadcaster
            # Host can be: broadcaster (communication_mode=0, is_host=True) OR communication host (communication_mode=1, is_host=True)
            if session.is_host:
                channel_stats[channel]['is_host'] = True
            if session.join_time > channel_stats[channel]['last_activity']:
                channel_stats[channel]['last_activity'] = session.join_time
        
        for channel, stats in channel_stats.items():
            channels_list.append({
                'channel_name': channel,
                'total_minutes': round(stats['total_minutes'], 2),
                'session_count': stats['session_count'],
                'role_switches': stats['role_switches'],
                'is_host': stats['is_host'],
                'last_activity': stats['last_activity'].isoformat()
            })
        
        # Quality insights
        quality_insights = []
        if spike_detection_score > 0.1:
            quality_insights.append(f"⚠️ User {uid} experienced {churn_events} abnormal leaves (reason 999). Suggested cause: network churn.")
        if failed_calls > 0:
            quality_insights.append(f"📞 {failed_calls} failed calls detected (duration < 5s)")
        if total_role_switches > 5:
            quality_insights.append(f"🔄 High role switching activity: {total_role_switches} switches")
        if avg_session_length < 1:
            quality_insights.append(f"⏱️ Short average session length: {avg_session_length:.1f} minutes")
        
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
            quality_insights=quality_insights
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
        
        # Calculate role analytics
        total_minutes = sum(s.duration_seconds or 0 for s in sessions) / 60.0
        host_minutes = sum((s.duration_seconds or 0) for s in sessions if s.is_host) / 60.0
        audience_minutes = total_minutes - host_minutes
        total_role_switches = sum(s.role_switches or 0 for s in sessions)
        
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
        
        # Quality indicators
        churn_events = len([s for s in sessions if s.reason == 999])
        failed_calls = len([s for s in sessions if (s.duration_seconds or 0) < 5])
        test_channels = 1 if len(set(s.uid for s in sessions)) == 1 else 0
        
        # Calculate max concurrent users (simplified - would need more complex logic for real implementation)
        max_concurrent_users = len(set(s.uid for s in sessions))
        
        # Calculate quality score (0-100)
        quality_score = 100
        if churn_events > 0:
            quality_score -= min(churn_events * 10, 50)
        if failed_calls > 0:
            quality_score -= min(failed_calls * 5, 30)
        if avg_user_session_length < 1:
            quality_score -= 20
        quality_score = max(0, quality_score)
        
        # Generate insights
        insights = []
        if churn_events > 0:
            insights.append(f"⚠️ {churn_events} churn events detected (reason=999)")
        if failed_calls > 0:
            insights.append(f"📞 {failed_calls} failed calls (duration < 5s)")
        if test_channels:
            insights.append("🧪 Test channel detected (only 1 user)")
        if avg_user_session_length < 1:
            insights.append(f"⏱️ Short average session length: {avg_user_session_length:.1f} minutes")
        if quality_score < 50:
            insights.append("🔴 Poor quality indicators detected")
        elif quality_score < 80:
            insights.append("🟡 Moderate quality indicators")
        else:
            insights.append("🟢 Good quality indicators")
        
        return QualityMetricsResponse(
            channel_name=channel_name,
            avg_user_session_length=round(avg_user_session_length, 2),
            avg_join_to_media_time=0.0,  # Would need additional tracking
            max_concurrent_users=max_concurrent_users,
            churn_events=churn_events,
            failed_calls=failed_calls,
            test_channels=test_channels,
            session_length_histogram=histogram,
            peak_concurrent_time=None,  # Would need additional tracking
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
            
            # Churn events (reason = 999)
            churn_events = len([s for s in user_session_list if s.reason == 999])
            
            user_analytics.append({
                'uid': uid,
                'total_channels_joined': total_channels,
                'total_active_minutes': round(total_minutes, 2),
                'total_role_switches': total_role_switches,
                'platform_distribution': platform_dist,
                'failed_calls': failed_calls,
                'churn_events': churn_events
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
    platform_map = {
        1: "Web",
        2: "iOS", 
        3: "Android",
        4: "Windows",
        5: "macOS",
        6: "Linux",
        7: "WebRTC"
    }
    return platform_map.get(platform_id, f"Platform {platform_id}")

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
async def export_data(app_id: str, request: ExportRequest, db: Session = Depends(get_db)):
    """Export data for a specific App ID with optional filters"""
    try:
        # Set the app_id from the URL path
        request.app_id = app_id
        
        # Parse string dates to datetime objects if they're strings
        if isinstance(request.start_date, str):
            request.start_date = datetime.fromisoformat(request.start_date.replace('Z', '+00:00'))
        if isinstance(request.end_date, str):
            request.end_date = datetime.fromisoformat(request.end_date.replace('Z', '+00:00'))
        
        # Validate export request for security
        validation_result = ExportSecurity.validate_export_request(request.dict())
        if not validation_result['valid']:
            raise HTTPException(status_code=400, detail=f"Export validation failed: {', '.join(validation_result['errors'])}")
        
        # Use sanitized data
        request = ExportRequest(**validation_result['sanitized_data'])
        
        # Validate request
        if not request.start_date and not request.end_date:
            # Default to last 7 days if no date range provided
            request.start_date = datetime.utcnow() - timedelta(days=7)
            request.end_date = datetime.utcnow()
        
        # Create export service
        export_service = ExportService(db)
        
        # Generate export
        export_result = export_service.export_data(request)
        
        logger.info(f"Export completed for app_id {app_id}: {export_result.get('export_info', {}).get('total_records', 0)} records")
        
        # Handle CSV export (zip file)
        if request.format.lower() == "csv" and "zip_file" in export_result:
            zip_data = export_result["zip_file"]
            filename = f"agora_export_{app_id}_{request.start_date.strftime('%Y%m%d')}_to_{request.end_date.strftime('%Y%m%d')}.zip"
            total_records = export_result.get('export_info', {}).get('total_records', 0)
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
async def validate_export_request(app_id: str, request: ExportRequest, db: Session = Depends(get_db)):
    """Validate export request and return limits information"""
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
        
        # Validate export limits
        validation_result = export_service.validate_export_limits(request)
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Error validating export request for {app_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/api/export/{app_id}/share")
async def create_public_share(app_id: str, request: ExportRequest, db: Session = Depends(get_db)):
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
