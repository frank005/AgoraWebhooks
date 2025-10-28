"""
Security configuration and utilities for Agora Webhooks Server
"""

import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

class SecurityConfig:
    """Security configuration settings"""
    
    # Rate limiting settings
    WEBHOOK_RATE_LIMIT = 1000  # requests per minute
    API_RATE_LIMIT = 100       # requests per minute
    EXPORT_RATE_LIMIT = 10     # exports per minute
    
    # Export limits
    MAX_EXPORT_RECORDS = 100000
    MAX_EXPORT_DAYS = 30
    CHUNK_THRESHOLD = 10000
    
    # Security headers
    SECURITY_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains"
    }
    
    # CORS settings (for production)
    ALLOWED_ORIGINS = [
        "https://your-domain.com",
        "https://www.your-domain.com"
    ]
    
    # Webhook validation
    WEBHOOK_TIMEOUT = 30  # seconds
    MAX_PAYLOAD_SIZE = 1024 * 1024  # 1MB

class RateLimiter:
    """Simple in-memory rate limiter (use Redis in production)"""
    
    def __init__(self):
        self.storage: Dict[str, list] = {}
    
    def is_allowed(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check if request is allowed based on rate limit"""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Clean old entries
        if key in self.storage:
            self.storage[key] = [
                timestamp for timestamp in self.storage[key]
                if timestamp > cutoff_time
            ]
        else:
            self.storage[key] = []
        
        # Check if under limit
        if len(self.storage[key]) >= max_requests:
            return False
        
        # Add current request
        self.storage[key].append(current_time)
        return True
    
    def get_remaining_requests(self, key: str, max_requests: int, window_seconds: int) -> int:
        """Get remaining requests in current window"""
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        if key in self.storage:
            self.storage[key] = [
                timestamp for timestamp in self.storage[key]
                if timestamp > cutoff_time
            ]
            return max(0, max_requests - len(self.storage[key]))
        
        return max_requests

class WebhookValidator:
    """Webhook payload validation and security checks"""
    
    @staticmethod
    def validate_payload_size(payload: str, max_size: int = SecurityConfig.MAX_PAYLOAD_SIZE) -> bool:
        """Validate webhook payload size"""
        return len(payload.encode('utf-8')) <= max_size
    
    @staticmethod
    def validate_app_id(app_id: str) -> bool:
        """Validate App ID format"""
        if not app_id or len(app_id) < 10:
            return False
        
        # Basic format validation (adjust based on your App ID format)
        return app_id.replace('-', '').replace('_', '').isalnum()
    
    @staticmethod
    def sanitize_input(input_str: str) -> str:
        """Basic input sanitization"""
        if not input_str:
            return ""
        
        # Remove potentially dangerous characters
        dangerous_chars = ['<', '>', '"', "'", '&', ';', '(', ')', '|', '`', '$']
        for char in dangerous_chars:
            input_str = input_str.replace(char, '')
        
        return input_str.strip()

class ExportSecurity:
    """Export-specific security measures"""
    
    @staticmethod
    def validate_export_request(request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate export request for security and limits"""
        errors = []
        warnings = []
        
        # Check date range
        if 'start_date' in request_data and 'end_date' in request_data:
            start_date = request_data['start_date']
            end_date = request_data['end_date']
            
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            date_diff = end_date - start_date
            if date_diff.days > SecurityConfig.MAX_EXPORT_DAYS:
                errors.append(f"Date range cannot exceed {SecurityConfig.MAX_EXPORT_DAYS} days")
        
        # Check app_id
        if not WebhookValidator.validate_app_id(request_data.get('app_id', '')):
            errors.append("Invalid App ID format")
        
        # Check channel name if provided
        if 'channel_name' in request_data and request_data['channel_name']:
            sanitized_channel = WebhookValidator.sanitize_input(request_data['channel_name'])
            if sanitized_channel != request_data['channel_name']:
                warnings.append("Channel name was sanitized")
                request_data['channel_name'] = sanitized_channel
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'sanitized_data': request_data
        }

# Global rate limiter instance
rate_limiter = RateLimiter()

def get_rate_limit_headers(key: str, max_requests: int, window_seconds: int) -> Dict[str, str]:
    """Get rate limit headers for response"""
    remaining = rate_limiter.get_remaining_requests(key, max_requests, window_seconds)
    
    return {
        "X-RateLimit-Limit": str(max_requests),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(int(time.time() + window_seconds))
    }