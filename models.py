from pydantic import BaseModel
from typing import Optional, List, Union
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

class WebhookRequest(BaseModel):
    """Pydantic model for complete Agora webhook request"""
    noticeId: str
    productId: int
    eventType: int
    notifyMs: Optional[int] = None  # Timestamp when notification was sent
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
    channel_session_id: Optional[str]
    total_minutes: float
    unique_users: int
    last_activity: datetime

class ChannelDetailResponse(BaseModel):
    """Response model for detailed channel information"""
    channel_name: str
    total_minutes: float
    unique_users: int
    sessions: List[ChannelSessionResponse]
