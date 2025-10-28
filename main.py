import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
import uvicorn

from config import Config
from database import get_db, create_tables, ChannelSession, ChannelMetrics, UserMetrics, WebhookEvent
from models import WebhookRequest, ChannelSessionResponse, ChannelMetricsResponse, UserMetricsResponse, ChannelListResponse, ChannelDetailResponse, ExportRequest, ExportResponse
from webhook_processor import WebhookProcessor
from export_service import ExportService

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
            func.max(ChannelSession.leave_time).label('last_activity'),
            func.array_agg(func.distinct(ChannelSession.client_type)).label('client_types')
        ).filter(
            ChannelSession.app_id == app_id,
            ChannelSession.duration_seconds.isnot(None)  # Only include completed sessions
        ).group_by(ChannelSession.channel_name, ChannelSession.channel_session_id).order_by(desc('last_activity')).offset(offset).limit(per_page).all()
        
        channels = []
        for session in channel_sessions:
            # Keep channel name simple - no time ranges in the name
            display_name = session.channel_name
            
            # Convert seconds to minutes
            total_minutes = (session.total_seconds or 0) / 60.0
            
            # Filter out None values from client_types array
            client_types = [ct for ct in (session.client_types or []) if ct is not None]
            
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
