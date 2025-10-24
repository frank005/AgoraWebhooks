import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import uvicorn

from config import Config
from database import get_db, create_tables, ChannelSession, ChannelMetrics, UserMetrics
from models import WebhookRequest, ChannelSessionResponse, ChannelMetricsResponse, UserMetricsResponse, ChannelListResponse, ChannelDetailResponse
from webhook_processor import WebhookProcessor

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

# Initialize database on startup
create_tables()
logger.info("Database tables created/verified")

# Templates for web interface
templates = Jinja2Templates(directory="templates")

@app.post("/{app_id}/webhooks")
async def receive_webhook(app_id: str, request: Request):
    """Receive webhook from Agora for specific App ID"""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    logger.info(f"Received webhook from {client_ip} for app_id: {app_id}, User-Agent: {user_agent}")
    
    try:
        # Get raw body
        body = await request.body()
        logger.debug(f"Webhook body length: {len(body)} bytes")
        
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
        
        logger.info(f"Webhook processed successfully for app_id: {app_id}, event_type: {webhook_data.eventType}, from: {client_ip}")
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
async def get_channels(app_id: str, db: Session = Depends(get_db)):
    """Get list of channels for an App ID"""
    try:
        # Get channel metrics aggregated by channel session
        channel_metrics = db.query(
            ChannelMetrics.channel_name,
            ChannelMetrics.channel_session_id,
            func.sum(ChannelMetrics.total_minutes).label('total_minutes'),
            func.max(ChannelMetrics.unique_users).label('unique_users'),
            func.max(ChannelMetrics.updated_at).label('last_activity')
        ).filter(
            ChannelMetrics.app_id == app_id
        ).group_by(ChannelMetrics.channel_name, ChannelMetrics.channel_session_id).order_by(desc('last_activity')).all()
        
        channels = []
        for metric in channel_metrics:
            # Create a display name that includes session info if there are multiple sessions
            display_name = metric.channel_name
            if metric.channel_session_id:
                # Extract session number from session ID (last part after underscore)
                session_parts = metric.channel_session_id.split('_')
                if len(session_parts) > 2:
                    session_num = session_parts[-1]
                    display_name = f"{metric.channel_name} (Session {session_num})"
            
            channels.append(ChannelListResponse(
                channel_name=display_name,
                channel_session_id=metric.channel_session_id,
                total_minutes=float(metric.total_minutes or 0),
                unique_users=metric.unique_users or 0,
                last_activity=metric.last_activity
            ))
        
        return {"channels": channels}
        
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
                duration_minutes=session.duration_seconds / 60.0 if session.duration_seconds else None
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

if __name__ == "__main__":
    # Create templates directory if it doesn't exist
    import os
    os.makedirs("templates", exist_ok=True)
    
    # SSL configuration
    ssl_kwargs = {}
    if Config.SSL_CERT_PATH and Config.SSL_KEY_PATH:
        ssl_kwargs = {
            "ssl_certfile": Config.SSL_CERT_PATH,
            "ssl_keyfile": Config.SSL_KEY_PATH
        }
        logger.info(f"Starting server with SSL on {Config.HOST}:{Config.PORT}")
    else:
        logger.info(f"Starting server without SSL on {Config.HOST}:{Config.PORT}")
    
    uvicorn.run(
        "main:app",
        host=Config.HOST,
        port=Config.PORT,
        reload=False,
        **ssl_kwargs
    )
