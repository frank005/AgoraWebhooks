#!/usr/bin/env python3
"""
Script to list all unique app_ids from the database
"""
from sqlalchemy import distinct
from database import SessionLocal, WebhookEvent, ChannelSession, ChannelMetrics, UserMetrics, UserAnalytics, RoleEvent, QualityMetrics

def get_all_appids():
    """Get all unique app_ids from all tables"""
    db = SessionLocal()
    try:
        appids = set()
        
        # Get app_ids from WebhookEvent table
        webhook_appids = db.query(distinct(WebhookEvent.app_id)).all()
        appids.update([appid[0] for appid in webhook_appids if appid[0]])
        
        # Get app_ids from ChannelSession table
        channel_appids = db.query(distinct(ChannelSession.app_id)).all()
        appids.update([appid[0] for appid in channel_appids if appid[0]])
        
        # Get app_ids from ChannelMetrics table
        metrics_appids = db.query(distinct(ChannelMetrics.app_id)).all()
        appids.update([appid[0] for appid in metrics_appids if appid[0]])
        
        # Get app_ids from UserMetrics table
        user_metrics_appids = db.query(distinct(UserMetrics.app_id)).all()
        appids.update([appid[0] for appid in user_metrics_appids if appid[0]])
        
        # Get app_ids from UserAnalytics table
        user_analytics_appids = db.query(distinct(UserAnalytics.app_id)).all()
        appids.update([appid[0] for appid in user_analytics_appids if appid[0]])
        
        # Get app_ids from RoleEvent table
        role_appids = db.query(distinct(RoleEvent.app_id)).all()
        appids.update([appid[0] for appid in role_appids if appid[0]])
        
        # Get app_ids from QualityMetrics table
        quality_appids = db.query(distinct(QualityMetrics.app_id)).all()
        appids.update([appid[0] for appid in quality_appids if appid[0]])
        
        return sorted(list(appids))
    
    finally:
        db.close()

if __name__ == "__main__":
    print("Fetching all app_ids from the database...")
    appids = get_all_appids()
    
    if appids:
        print(f"\nFound {len(appids)} unique app_id(s):\n")
        for i, appid in enumerate(appids, 1):
            print(f"{i}. {appid}")
    else:
        print("\nNo app_ids found in the database.")