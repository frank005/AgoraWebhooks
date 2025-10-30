from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, Index, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from config import Config

# Database setup
engine = create_engine(Config.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class WebhookEvent(Base):
    """Raw webhook events from Agora"""
    __tablename__ = "webhook_events"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    notice_id = Column(String(100), unique=True, nullable=False, index=True)
    product_id = Column(Integer, nullable=False)
    event_type = Column(Integer, nullable=False, index=True)
    
    # Payload fields
    channel_name = Column(String(255), nullable=False, index=True)
    uid = Column(Integer, nullable=False, index=True)
    client_seq = Column(Integer, nullable=False)
    platform = Column(Integer)
    reason = Column(Integer)
    client_type = Column(Integer)
    ts = Column(Integer, nullable=False, index=True)  # Unix timestamp
    duration = Column(Integer)  # Duration in seconds
    
    # Channel session tracking
    channel_session_id = Column(String(100), nullable=True, index=True)
    
    # Metadata
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    raw_payload = Column(Text)  # Store original JSON payload
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_app_channel_ts', 'app_id', 'channel_name', 'ts'),
        Index('idx_app_uid_ts', 'app_id', 'uid', 'ts'),
        Index('idx_app_event_ts', 'app_id', 'event_type', 'ts'),
    )

class ChannelSession(Base):
    """Calculated channel sessions with join/leave times"""
    __tablename__ = "channel_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    channel_name = Column(String(255), nullable=False, index=True)
    uid = Column(Integer, nullable=False, index=True)
    
    # Channel session tracking
    channel_session_id = Column(String(100), nullable=True, index=True)
    
    # Session ID from Agora
    sid = Column(String(100), nullable=True, index=True)
    
    # Session timing
    join_time = Column(DateTime, nullable=False, index=True)
    leave_time = Column(DateTime, nullable=True, index=True)
    duration_seconds = Column(Integer, nullable=True)  # Calculated duration
    
    # Per-user ordering (for clientSeq)
    last_client_seq = Column(Integer, nullable=True)  # Last clientSeq processed for this user
    
    # Additional fields from webhook
    product_id = Column(Integer, nullable=True)
    platform = Column(Integer, nullable=True)
    reason = Column(Integer, nullable=True)
    client_type = Column(Integer, nullable=True)
    
    # Role and communication mode tracking
    communication_mode = Column(Integer, nullable=True)  # 0=audience, 1=host/broadcaster
    role_switches = Column(Integer, default=0)  # Count of role changes for this user
    is_host = Column(Boolean, default=False)  # Current role (host/audience)
    
    # Quality metrics
    join_to_media_time = Column(Integer, nullable=True)  # Time from join to first media (seconds)
    session_quality_score = Column(Float, nullable=True)  # Calculated quality score
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_app_channel_uid', 'app_id', 'channel_name', 'uid'),
        Index('idx_app_join_time', 'app_id', 'join_time'),
    )

class ChannelMetrics(Base):
    """Aggregated metrics per channel"""
    __tablename__ = "channel_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    channel_name = Column(String(255), nullable=False, index=True)
    channel_session_id = Column(String(100), nullable=True, index=True)
    date = Column(DateTime, nullable=False, index=True)  # Date for daily aggregation
    
    # Metrics
    total_users = Column(Integer, default=0)
    total_minutes = Column(Float, default=0.0)
    unique_users = Column(Integer, default=0)
    
    # Activity tracking
    first_activity = Column(DateTime, nullable=True)
    last_activity = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (
        Index('idx_app_channel_session_date', 'app_id', 'channel_name', 'channel_session_id', 'date', unique=True),
    )

class UserMetrics(Base):
    """Aggregated metrics per user"""
    __tablename__ = "user_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    uid = Column(Integer, nullable=False, index=True)
    channel_name = Column(String(255), nullable=False, index=True)
    channel_session_id = Column(String(100), nullable=True, index=True)
    date = Column(DateTime, nullable=False, index=True)  # Date for daily aggregation
    
    # Metrics
    total_minutes = Column(Float, default=0.0)
    session_count = Column(Integer, default=0)
    
    # Role analytics
    host_minutes = Column(Float, default=0.0)
    audience_minutes = Column(Float, default=0.0)
    role_switches = Column(Integer, default=0)
    
    # Platform analytics
    platform_distribution = Column(Text)  # JSON string of platform usage
    
    # Quality metrics
    avg_session_length = Column(Float, default=0.0)
    avg_join_to_media_time = Column(Float, default=0.0)
    churn_events = Column(Integer, default=0)  # reason=999 events
    failed_calls = Column(Integer, default=0)  # sessions < 5 seconds
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (
        Index('idx_app_uid_channel_date', 'app_id', 'uid', 'channel_name', 'date', unique=True),
    )

class UserAnalytics(Base):
    """Comprehensive user analytics and insights"""
    __tablename__ = "user_analytics"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    uid = Column(Integer, nullable=False, index=True)
    
    # Overall metrics
    total_channels_joined = Column(Integer, default=0)
    total_active_minutes = Column(Float, default=0.0)
    total_role_switches = Column(Integer, default=0)
    
    # Platform distribution (JSON)
    platform_distribution = Column(Text)  # {"web": 120, "ios": 60, "android": 30}
    
    # Quality indicators
    avg_session_length = Column(Float, default=0.0)
    spike_detection_score = Column(Float, default=0.0)  # Frequency of reason=999 events
    churn_events = Column(Integer, default=0)
    failed_calls = Column(Integer, default=0)
    
    # Product usage breakdown
    rtc_minutes = Column(Float, default=0.0)
    cloud_recording_minutes = Column(Float, default=0.0)
    media_push_minutes = Column(Float, default=0.0)
    media_pull_minutes = Column(Float, default=0.0)
    conversational_ai_minutes = Column(Float, default=0.0)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (
        Index('idx_app_uid_unique', 'app_id', 'uid', unique=True),
    )

class RoleEvent(Base):
    """Role change events (111/112) to track role switches"""
    __tablename__ = "role_events"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    channel_name = Column(String(255), nullable=False, index=True)
    channel_session_id = Column(String(100), nullable=True, index=True)
    uid = Column(Integer, nullable=False, index=True)
    ts = Column(Integer, nullable=False, index=True)  # Unix timestamp
    new_role = Column(Integer, nullable=False)  # 111=broadcaster, 112=audience
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Indexes
    __table_args__ = (
        Index('idx_role_channel_session_uid_ts', 'channel_session_id', 'uid', 'ts'),
    )

class QualityMetrics(Base):
    """Channel and session quality metrics"""
    __tablename__ = "quality_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    app_id = Column(String(50), nullable=False, index=True)
    channel_name = Column(String(255), nullable=False, index=True)
    channel_session_id = Column(String(100), nullable=True, index=True)
    date = Column(DateTime, nullable=False, index=True)
    
    # Quality indicators
    avg_user_session_length = Column(Float, default=0.0)
    avg_join_to_media_time = Column(Float, default=0.0)
    max_concurrent_users = Column(Integer, default=0)
    churn_events = Column(Integer, default=0)
    failed_calls = Column(Integer, default=0)
    test_channels = Column(Integer, default=0)  # Channels with only 1 user
    
    # Session length histogram (JSON)
    session_length_histogram = Column(Text)  # {"0-5s": 10, "5-30s": 25, "30-60s": 15}
    
    # Performance data
    peak_concurrent_time = Column(DateTime, nullable=True)
    first_media_time = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (
        Index('idx_app_channel_session_date', 'app_id', 'channel_name', 'channel_session_id', 'date', unique=True),
    )

def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
