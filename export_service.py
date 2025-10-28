"""
Export service for Agora webhook data
Handles data export with various filters and formats
"""

import csv
import json
import logging
import uuid
import zipfile
import io
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from io import StringIO, BytesIO
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from database import WebhookEvent, ChannelSession, ChannelMetrics, UserMetrics
from models import ExportRequest, ExportResponse
from mappings import get_platform_name, get_product_name

logger = logging.getLogger(__name__)

class ExportService:
    """Service for exporting webhook data in various formats"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def export_data(self, request: ExportRequest) -> Dict[str, Any]:
        """Export data based on the request parameters"""
        
        # Validate date range (max 30 days to prevent database lockup)
        if request.start_date and request.end_date:
            date_diff = request.end_date - request.start_date
            if date_diff.days > 30:
                raise ValueError("Date range cannot exceed 30 days")
        
        # Set default date range if not provided (last 7 days)
        if not request.start_date:
            request.start_date = datetime.utcnow() - timedelta(days=7)
        if not request.end_date:
            request.end_date = datetime.utcnow()
        
        # Add one day to end_date to include the full day
        end_date_inclusive = request.end_date + timedelta(days=1)
        
        export_id = str(uuid.uuid4())
        export_data = {
            "export_id": export_id,
            "app_id": request.app_id,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "channel_filter": request.channel_name,
            "created_at": datetime.utcnow().isoformat(),
            "webhook_events": [],
            "sessions": [],
            "channel_metrics": [],
            "user_metrics": []
        }
        
        # Build base query filters
        base_filters = [
            WebhookEvent.app_id == request.app_id,
            WebhookEvent.received_at >= request.start_date,
            WebhookEvent.received_at < end_date_inclusive
        ]
        
        if request.channel_name:
            base_filters.append(WebhookEvent.channel_name == request.channel_name)
        
        # Export webhook events
        if request.include_webhook_events:
            webhook_events = self.db.query(WebhookEvent).filter(and_(*base_filters)).all()
            export_data["webhook_events"] = [self._format_webhook_event(event) for event in webhook_events]
            export_data["webhook_events_count"] = len(webhook_events)
        else:
            export_data["webhook_events_count"] = 0
        
        # Export sessions
        if request.include_sessions:
            session_filters = [
                ChannelSession.app_id == request.app_id,
                ChannelSession.join_time >= request.start_date,
                ChannelSession.join_time < end_date_inclusive
            ]
            
            if request.channel_name:
                session_filters.append(ChannelSession.channel_name == request.channel_name)
            
            sessions = self.db.query(ChannelSession).filter(and_(*session_filters)).all()
            export_data["sessions"] = [self._format_session(session) for session in sessions]
            export_data["sessions_count"] = len(sessions)
        else:
            export_data["sessions_count"] = 0
        
        # Export channel metrics
        if request.include_metrics:
            # Channel metrics filters
            channel_metrics_filters = [
                ChannelMetrics.app_id == request.app_id,
                ChannelMetrics.date >= request.start_date,
                ChannelMetrics.date < end_date_inclusive
            ]
            
            if request.channel_name:
                channel_metrics_filters.append(ChannelMetrics.channel_name == request.channel_name)
            
            channel_metrics = self.db.query(ChannelMetrics).filter(and_(*channel_metrics_filters)).all()
            export_data["channel_metrics"] = [self._format_channel_metrics(metric) for metric in channel_metrics]
            
            # User metrics filters (separate to ensure proper channel filtering)
            user_metrics_filters = [
                UserMetrics.app_id == request.app_id,
                UserMetrics.date >= request.start_date,
                UserMetrics.date < end_date_inclusive
            ]
            
            if request.channel_name:
                user_metrics_filters.append(UserMetrics.channel_name == request.channel_name)
            
            user_metrics = self.db.query(UserMetrics).filter(and_(*user_metrics_filters)).all()
            export_data["user_metrics"] = [self._format_user_metrics(metric) for metric in user_metrics]
            
            export_data["metrics_count"] = len(channel_metrics) + len(user_metrics)
        else:
            export_data["metrics_count"] = 0
        
        export_data["total_records"] = (
            export_data["webhook_events_count"] + 
            export_data["sessions_count"] + 
            export_data["metrics_count"]
        )
        
        # Generate response based on format
        if request.format.lower() == "csv":
            return self._generate_csv_export(export_data)
        else:
            return self._generate_json_export(export_data)
    
    def _format_webhook_event(self, event: WebhookEvent) -> Dict[str, Any]:
        """Format webhook event for export"""
        return {
            "id": event.id,
            "app_id": event.app_id,
            "notice_id": event.notice_id,
            "product_id": event.product_id,
            "product_name": get_product_name(event.product_id),
            "event_type": event.event_type,
            "event_type_name": self._get_event_type_name(event.event_type),
            "channel_name": event.channel_name,
            "uid": event.uid,
            "client_seq": event.client_seq,
            "platform": event.platform,
            "platform_name": get_platform_name(event.platform, event.client_type),
            "reason": event.reason,
            "client_type": event.client_type,
            "timestamp": event.ts,
            "timestamp_utc": datetime.fromtimestamp(event.ts).isoformat() if event.ts else None,
            "duration": event.duration,
            "channel_session_id": event.channel_session_id,
            "received_at": event.received_at.isoformat() if event.received_at else None,
            "raw_payload": event.raw_payload
        }
    
    def _format_session(self, session: ChannelSession) -> Dict[str, Any]:
        """Format session for export"""
        return {
            "id": session.id,
            "app_id": session.app_id,
            "channel_name": session.channel_name,
            "uid": session.uid,
            "channel_session_id": session.channel_session_id,
            "join_time": session.join_time.isoformat() if session.join_time else None,
            "leave_time": session.leave_time.isoformat() if session.leave_time else None,
            "duration_seconds": session.duration_seconds,
            "duration_minutes": session.duration_seconds / 60.0 if session.duration_seconds else None,
            "last_client_seq": session.last_client_seq,
            "product_id": session.product_id,
            "product_name": get_product_name(session.product_id),
            "platform": session.platform,
            "platform_name": get_platform_name(session.platform, session.client_type),
            "reason": session.reason,
            "client_type": session.client_type,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None
        }
    
    def _format_channel_metrics(self, metric: ChannelMetrics) -> Dict[str, Any]:
        """Format channel metrics for export"""
        return {
            "id": metric.id,
            "app_id": metric.app_id,
            "channel_name": metric.channel_name,
            "channel_session_id": metric.channel_session_id,
            "date": metric.date.isoformat() if metric.date else None,
            "total_users": metric.total_users,
            "total_minutes": metric.total_minutes,
            "unique_users": metric.unique_users,
            "first_activity": metric.first_activity.isoformat() if metric.first_activity else None,
            "last_activity": metric.last_activity.isoformat() if metric.last_activity else None,
            "created_at": metric.created_at.isoformat() if metric.created_at else None,
            "updated_at": metric.updated_at.isoformat() if metric.updated_at else None
        }
    
    def _format_user_metrics(self, metric: UserMetrics) -> Dict[str, Any]:
        """Format user metrics for export"""
        return {
            "id": metric.id,
            "app_id": metric.app_id,
            "uid": metric.uid,
            "channel_name": metric.channel_name,
            "channel_session_id": metric.channel_session_id,
            "date": metric.date.isoformat() if metric.date else None,
            "total_minutes": metric.total_minutes,
            "session_count": metric.session_count,
            "created_at": metric.created_at.isoformat() if metric.created_at else None,
            "updated_at": metric.updated_at.isoformat() if metric.updated_at else None
        }
    
    def _get_event_type_name(self, event_type: int) -> str:
        """Get human-readable event type name"""
        event_types = {
            1: "User Joined Channel",
            2: "User Left Channel", 
            103: "User Joined Channel (RTC)",
            104: "User Left Channel (RTC)",
            105: "User Joined Channel (Recording)",
            106: "User Left Channel (Recording)"
        }
        return event_types.get(event_type, f"Unknown Event ({event_type})")
    
    def _generate_json_export(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Generate JSON export"""
        return {
            "export_info": {
                "export_id": data["export_id"],
                "app_id": data["app_id"],
                "start_date": data["start_date"],
                "end_date": data["end_date"],
                "channel_filter": data["channel_filter"],
                "created_at": data["created_at"],
                "total_records": data["total_records"],
                "webhook_events_count": data["webhook_events_count"],
                "sessions_count": data["sessions_count"],
                "metrics_count": data["metrics_count"]
            },
            "data": {
                "webhook_events": data["webhook_events"],
                "sessions": data["sessions"],
                "channel_metrics": data["channel_metrics"],
                "user_metrics": data["user_metrics"]
            }
        }
    
    def _generate_csv_export(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Generate CSV export files and return as zip"""
        csv_files = {}
        
        # Generate webhook events CSV
        if data["webhook_events"]:
            webhook_csv = self._create_csv_from_data(
                data["webhook_events"], 
                "webhook_events"
            )
            csv_files["webhook_events.csv"] = webhook_csv
        
        # Generate sessions CSV
        if data["sessions"]:
            sessions_csv = self._create_csv_from_data(
                data["sessions"], 
                "sessions"
            )
            csv_files["sessions.csv"] = sessions_csv
        
        # Generate channel metrics CSV
        if data["channel_metrics"]:
            channel_metrics_csv = self._create_csv_from_data(
                data["channel_metrics"], 
                "channel_metrics"
            )
            csv_files["channel_metrics.csv"] = channel_metrics_csv
        
        # Generate user metrics CSV
        if data["user_metrics"]:
            user_metrics_csv = self._create_csv_from_data(
                data["user_metrics"], 
                "user_metrics"
            )
            csv_files["user_metrics.csv"] = user_metrics_csv
        
        # Create zip file
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for filename, csv_content in csv_files.items():
                zip_file.writestr(filename, csv_content)
        
        zip_buffer.seek(0)
        return {
            "export_info": {
                "export_id": data["export_id"],
                "app_id": data["app_id"],
                "start_date": data["start_date"],
                "end_date": data["end_date"],
                "channel_filter": data["channel_filter"],
                "created_at": data["created_at"],
                "total_records": data["total_records"],
                "webhook_events_count": data["webhook_events_count"],
                "sessions_count": data["sessions_count"],
                "metrics_count": data["metrics_count"]
            },
            "zip_file": zip_buffer.getvalue()
        }
    
    def _create_csv_from_data(self, data: List[Dict[str, Any]], data_type: str) -> str:
        """Create CSV string from data list"""
        if not data:
            return ""
        
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        return output.getvalue()