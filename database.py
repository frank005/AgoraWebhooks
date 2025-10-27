from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, Text, Index
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
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Unique constraint
    __table_args__ = (
        Index('idx_app_uid_channel_date', 'app_id', 'uid', 'channel_name', 'date', unique=True),
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
