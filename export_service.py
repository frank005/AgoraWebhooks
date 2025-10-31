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

from database import WebhookEvent, ChannelSession, ChannelMetrics, UserMetrics, RoleEvent
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
        
        # Check if we need chunked export for large datasets
        total_records = self._estimate_total_records(request, end_date_inclusive)
        if total_records > 10000 and request.format == "csv":
            return self._export_chunked_csv(request, end_date_inclusive, total_records)
        
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
            "user_metrics": [],
            "role_events": []
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
        
        # Export role events (111/112 role change events)
        if request.include_webhook_events:  # Include role events when webhook events are included
            role_events_filters = [
                RoleEvent.app_id == request.app_id,
                RoleEvent.created_at >= request.start_date,
                RoleEvent.created_at < end_date_inclusive
            ]
            
            if request.channel_name:
                role_events_filters.append(RoleEvent.channel_name == request.channel_name)
            
            role_events = self.db.query(RoleEvent).filter(and_(*role_events_filters)).all()
            export_data["role_events"] = [self._format_role_event(event) for event in role_events]
            export_data["role_events_count"] = len(role_events)
        else:
            export_data["role_events_count"] = 0
        
        export_data["total_records"] = (
            export_data["webhook_events_count"] + 
            export_data["sessions_count"] + 
            export_data["metrics_count"] +
            export_data["role_events_count"]
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
            "account": session.account,  # Account field from webhook payload (string UID)
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
        return event_types.get(event_type, f"Unknown Event ({event_type})")
    
    def _format_role_event(self, event: RoleEvent) -> Dict[str, Any]:
        """Format role event for export"""
        return {
            "id": event.id,
            "app_id": event.app_id,
            "channel_name": event.channel_name,
            "channel_session_id": event.channel_session_id,
            "uid": event.uid,
            "timestamp": event.ts,
            "timestamp_utc": datetime.fromtimestamp(event.ts).isoformat() if event.ts else None,
            "new_role": event.new_role,
            "new_role_name": "Broadcaster" if event.new_role == 111 else "Audience" if event.new_role == 112 else f"Unknown ({event.new_role})",
            "created_at": event.created_at.isoformat() if event.created_at else None
        }
    
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
                "metrics_count": data["metrics_count"],
                "role_events_count": data["role_events_count"]
            },
            "data": {
                "webhook_events": data["webhook_events"],
                "sessions": data["sessions"],
                "channel_metrics": data["channel_metrics"],
                "user_metrics": data["user_metrics"],
                "role_events": data["role_events"]
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
        
        # Generate role events CSV
        if data["role_events"]:
            role_events_csv = self._create_csv_from_data(
                data["role_events"], 
                "role_events"
            )
            csv_files["role_events.csv"] = role_events_csv
        
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
                "metrics_count": data["metrics_count"],
                "role_events_count": data["role_events_count"]
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
    
    def _estimate_total_records(self, request: ExportRequest, end_date_inclusive: datetime) -> int:
        """Estimate total number of records for the export"""
        total = 0
        
        # Build base query conditions
        conditions = [
            WebhookEvent.app_id == request.app_id,
            WebhookEvent.ts >= int(request.start_date.timestamp()),
            WebhookEvent.ts < int(end_date_inclusive.timestamp())
        ]
        
        if request.channel_name:
            conditions.append(WebhookEvent.channel_name == request.channel_name)
        
        # Count webhook events
        if request.include_webhook_events:
            total += self.db.query(WebhookEvent).filter(and_(*conditions)).count()
        
        # Count sessions
        if request.include_sessions:
            session_conditions = [
                ChannelSession.app_id == request.app_id,
                ChannelSession.join_time >= request.start_date,
                ChannelSession.join_time < end_date_inclusive
            ]
            if request.channel_name:
                session_conditions.append(ChannelSession.channel_name == request.channel_name)
            total += self.db.query(ChannelSession).filter(and_(*session_conditions)).count()
        
        # Count metrics
        if request.include_metrics:
            # Channel metrics
            channel_metric_conditions = [
                ChannelMetrics.app_id == request.app_id,
                ChannelMetrics.date >= request.start_date,
                ChannelMetrics.date < end_date_inclusive
            ]
            if request.channel_name:
                channel_metric_conditions.append(ChannelMetrics.channel_name == request.channel_name)
            total += self.db.query(ChannelMetrics).filter(and_(*channel_metric_conditions)).count()
            
            # User metrics
            user_metric_conditions = [
                UserMetrics.app_id == request.app_id,
                UserMetrics.date >= request.start_date,
                UserMetrics.date < end_date_inclusive
            ]
            if request.channel_name:
                user_metric_conditions.append(UserMetrics.channel_name == request.channel_name)
            total += self.db.query(UserMetrics).filter(and_(*user_metric_conditions)).count()
        
        return total
    
    def _export_chunked_csv(self, request: ExportRequest, end_date_inclusive: datetime, total_records: int) -> Dict[str, Any]:
        """Export large datasets in chunks to prevent database lockup"""
        chunk_size = 5000  # Process 5000 records at a time
        total_chunks = (total_records + chunk_size - 1) // chunk_size
        
        logger.info(f"Exporting {total_records} records in {total_chunks} chunks of {chunk_size}")
        
        # Create zip file for chunks
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Export webhook events in chunks
            if request.include_webhook_events:
                self._export_webhook_events_chunked(request, end_date_inclusive, chunk_size, zip_file)
            
            # Export sessions in chunks
            if request.include_sessions:
                self._export_sessions_chunked(request, end_date_inclusive, chunk_size, zip_file)
            
            # Export metrics in chunks
            if request.include_metrics:
                self._export_metrics_chunked(request, end_date_inclusive, chunk_size, zip_file)
        
        zip_buffer.seek(0)
        return {
            "zip_content": zip_buffer.getvalue(),
            "content_type": "application/zip",
            "filename": f"agora_export_chunked_{request.app_id}_{request.start_date.strftime('%Y%m%d')}_{request.end_date.strftime('%Y%m%d')}.zip",
            "total_records": total_records,
            "chunks": total_chunks
        }
    
    def _export_webhook_events_chunked(self, request: ExportRequest, end_date_inclusive: datetime, chunk_size: int, zip_file):
        """Export webhook events in chunks"""
        offset = 0
        chunk_num = 1
        
        while True:
            # Build query conditions
            conditions = [
                WebhookEvent.app_id == request.app_id,
                WebhookEvent.ts >= int(request.start_date.timestamp()),
                WebhookEvent.ts < int(end_date_inclusive.timestamp())
            ]
            
            if request.channel_name:
                conditions.append(WebhookEvent.channel_name == request.channel_name)
            
            # Get chunk of webhook events
            events = self.db.query(WebhookEvent).filter(and_(*conditions)).offset(offset).limit(chunk_size).all()
            
            if not events:
                break
            
            # Convert to export format
            events_data = [self._format_webhook_event(event) for event in events]
            
            # Create CSV for this chunk
            csv_content = self._create_csv_from_data(events_data, "webhook_events")
            zip_file.writestr(f"webhook_events_chunk_{chunk_num:03d}.csv", csv_content)
            
            offset += chunk_size
            chunk_num += 1
            
            logger.info(f"Exported webhook events chunk {chunk_num - 1}")
    
    def _export_sessions_chunked(self, request: ExportRequest, end_date_inclusive: datetime, chunk_size: int, zip_file):
        """Export sessions in chunks"""
        offset = 0
        chunk_num = 1
        
        while True:
            # Build query conditions
            conditions = [
                ChannelSession.app_id == request.app_id,
                ChannelSession.join_time >= request.start_date,
                ChannelSession.join_time < end_date_inclusive
            ]
            
            if request.channel_name:
                conditions.append(ChannelSession.channel_name == request.channel_name)
            
            # Get chunk of sessions
            sessions = self.db.query(ChannelSession).filter(and_(*conditions)).offset(offset).limit(chunk_size).all()
            
            if not sessions:
                break
            
            # Convert to export format
            sessions_data = [self._format_channel_session(session) for session in sessions]
            
            # Create CSV for this chunk
            csv_content = self._create_csv_from_data(sessions_data, "sessions")
            zip_file.writestr(f"sessions_chunk_{chunk_num:03d}.csv", csv_content)
            
            offset += chunk_size
            chunk_num += 1
            
            logger.info(f"Exported sessions chunk {chunk_num - 1}")
    
    def _export_metrics_chunked(self, request: ExportRequest, end_date_inclusive: datetime, chunk_size: int, zip_file):
        """Export metrics in chunks"""
        # Export channel metrics
        self._export_channel_metrics_chunked(request, end_date_inclusive, chunk_size, zip_file)
        
        # Export user metrics
        self._export_user_metrics_chunked(request, end_date_inclusive, chunk_size, zip_file)
    
    def _export_channel_metrics_chunked(self, request: ExportRequest, end_date_inclusive: datetime, chunk_size: int, zip_file):
        """Export channel metrics in chunks"""
        offset = 0
        chunk_num = 1
        
        while True:
            # Build query conditions
            conditions = [
                ChannelMetrics.app_id == request.app_id,
                ChannelMetrics.date >= request.start_date,
                ChannelMetrics.date < end_date_inclusive
            ]
            
            if request.channel_name:
                conditions.append(ChannelMetrics.channel_name == request.channel_name)
            
            # Get chunk of channel metrics
            metrics = self.db.query(ChannelMetrics).filter(and_(*conditions)).offset(offset).limit(chunk_size).all()
            
            if not metrics:
                break
            
            # Convert to export format
            metrics_data = [self._format_channel_metrics(metric) for metric in metrics]
            
            # Create CSV for this chunk
            csv_content = self._create_csv_from_data(metrics_data, "channel_metrics")
            zip_file.writestr(f"channel_metrics_chunk_{chunk_num:03d}.csv", csv_content)
            
            offset += chunk_size
            chunk_num += 1
            
            logger.info(f"Exported channel metrics chunk {chunk_num - 1}")
    
    def _export_user_metrics_chunked(self, request: ExportRequest, end_date_inclusive: datetime, chunk_size: int, zip_file):
        """Export user metrics in chunks"""
        offset = 0
        chunk_num = 1
        
        while True:
            # Build query conditions
            conditions = [
                UserMetrics.app_id == request.app_id,
                UserMetrics.date >= request.start_date,
                UserMetrics.date < end_date_inclusive
            ]
            
            if request.channel_name:
                conditions.append(UserMetrics.channel_name == request.channel_name)
            
            # Get chunk of user metrics
            metrics = self.db.query(UserMetrics).filter(and_(*conditions)).offset(offset).limit(chunk_size).all()
            
            if not metrics:
                break
            
            # Convert to export format
            metrics_data = [self._format_user_metrics(metric) for metric in metrics]
            
            # Create CSV for this chunk
            csv_content = self._create_csv_from_data(metrics_data, "user_metrics")
            zip_file.writestr(f"user_metrics_chunk_{chunk_num:03d}.csv", csv_content)
            
            offset += chunk_size
            chunk_num += 1
            
            logger.info(f"Exported user metrics chunk {chunk_num - 1}")
    
    def create_public_share_url(self, request: ExportRequest, token: str) -> str:
        """Create a public share URL with read-only token"""
        # This would typically store the token in a database or cache
        # For now, we'll return a URL with the token
        base_url = "https://your-domain.com"  # This should be configurable
        return f"{base_url}/api/export/public/{token}"
    
    def validate_export_limits(self, request: ExportRequest) -> Dict[str, Any]:
        """Validate export request against limits"""
        # Estimate total records
        end_date_inclusive = request.end_date + timedelta(days=1) if request.end_date else datetime.utcnow() + timedelta(days=1)
        total_records = self._estimate_total_records(request, end_date_inclusive)
        
        # Check limits
        limits = {
            "max_records": 100000,  # Maximum records per export
            "max_days": 30,  # Maximum days per export
            "chunk_threshold": 10000  # Threshold for chunked export
        }
        
        # Calculate estimated file size (rough estimate)
        estimated_size_mb = total_records * 0.5  # Rough estimate: 0.5KB per record
        
        return {
            "total_records": total_records,
            "estimated_size_mb": round(estimated_size_mb, 2),
            "within_limits": total_records <= limits["max_records"],
            "needs_chunking": total_records > limits["chunk_threshold"],
            "limits": limits
        }