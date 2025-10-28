from pydantic import BaseModel
from typing import Optional, List, Union, Dict, Any
from datetime import datetime

class WebhookPayload(BaseModel):
    """Pydantic model for Agora webhook payload - flexible to handle different event types"""
    # Common fields
    channelName: str
    ts: int
    
    # Optional fields that may or may not be present depending on event type
    clientSeq: Optional[int] = None
    uid: Optional[int] = None
    platform: Optional[int] = None
    reason: Optional[int] = None
    duration: Optional[int] = None
    clientType: Optional[int] = None

class WebhookRequest(BaseModel):
    """Pydantic model for complete Agora webhook request"""
    noticeId: str
    productId: int
    eventType: int
    notifyMs: Optional[int] = None  # Timestamp when notification was sent
    sid: Optional[str] = None  # Session ID from Agora
    payload: WebhookPayload

class ChannelSessionResponse(BaseModel):
    """Response model for channel session data"""
    id: int
    app_id: str
    channel_name: str
    uid: int
    join_time: datetime
    leave_time: Optional[datetime]
    duration_seconds: Optional[int]
    duration_minutes: Optional[float]
    product_id: Optional[int]
    platform: Optional[int]
    reason: Optional[int]
    client_type: Optional[int]

class ChannelMetricsResponse(BaseModel):
    """Response model for channel metrics"""
    app_id: str
    channel_name: str
    date: datetime
    total_users: int
    total_minutes: float
    unique_users: int

class UserMetricsResponse(BaseModel):
    """Response model for user metrics"""
    app_id: str
    uid: int
    channel_name: str
    date: datetime
    total_minutes: float
    session_count: int

class ChannelListResponse(BaseModel):
    """Response model for channel list with basic info"""
    channel_name: str
    display_name: str
    channel_session_id: Optional[str]
    total_minutes: float
    unique_users: int
    first_activity: Optional[datetime]
    last_activity: Optional[datetime]
    client_types: Optional[List[int]] = None

class ChannelDetailResponse(BaseModel):
    """Response model for detailed channel information"""
    channel_name: str
    total_minutes: float
    unique_users: int
    sessions: List[ChannelSessionResponse]

class ExportRequest(BaseModel):
    """Request model for data export"""
    app_id: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    channel_name: Optional[str] = None
    format: str = "json"  # "json" or "csv"
    include_webhook_events: bool = True
    include_sessions: bool = True
    include_metrics: bool = True

class ExportResponse(BaseModel):
    """Response model for export data"""
    export_id: str
    total_records: int
    webhook_events_count: int
    sessions_count: int
    metrics_count: int
    date_range: str
    channel_filter: Optional[str] = None
    created_at: datetime

class UserDetailResponse(BaseModel):
    """Response model for detailed user analytics"""
    uid: int
    app_id: str
    total_channels_joined: int
    total_active_minutes: float
    total_role_switches: int
    platform_distribution: Dict[str, int]
    avg_session_length: float
    spike_detection_score: float
    churn_events: int
    failed_calls: int
    product_breakdown: Dict[str, float]
    channels_list: List[Dict[str, Any]]
    quality_insights: List[str]

class RoleAnalyticsResponse(BaseModel):
    """Response model for role and product analytics"""
    channel_name: str
    total_minutes: float
    host_minutes: float
    audience_minutes: float
    role_switches: int
    product_breakdown: Dict[str, float]
    platform_breakdown: Dict[str, float]

class QualityMetricsResponse(BaseModel):
    """Response model for quality and health indicators"""
    channel_name: str
    avg_user_session_length: float
    avg_join_to_media_time: float
    max_concurrent_users: int
    churn_events: int
    failed_calls: int
    test_channels: int
    session_length_histogram: Dict[str, int]
    peak_concurrent_time: Optional[datetime]
    quality_score: float
    insights: List[str]
