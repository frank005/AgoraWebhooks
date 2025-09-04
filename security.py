import hashlib
import hmac
import logging
from typing import Optional
from config import Config

logger = logging.getLogger(__name__)

class WebhookSecurity:
    """Handle webhook security and signature verification"""
    
    @staticmethod
    def verify_agora_signature(payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Verify Agora webhook signature using HMAC-SHA256
        
        Args:
            payload: Raw webhook payload bytes
            signature: Signature from Agora-Signature header
            secret: Webhook secret (uses config default if None)
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not secret:
            secret = Config.WEBHOOK_SECRET
            
        if not secret:
            logger.warning("No webhook secret configured, skipping signature verification")
            return True
        
        if not signature:
            logger.warning("No signature provided in webhook request")
            return False
        
        try:
            # Agora uses HMAC-SHA256 with the webhook secret
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Use constant-time comparison to prevent timing attacks
            is_valid = hmac.compare_digest(signature, expected_signature)
            
            if not is_valid:
                logger.warning(f"Invalid webhook signature. Expected: {expected_signature}, Got: {signature}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
    
    @staticmethod
    def verify_agora_signature_sha1(payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Verify Agora webhook signature using HMAC-SHA1 (legacy support)
        
        Args:
            payload: Raw webhook payload bytes
            signature: Signature from Agora-Signature header
            secret: Webhook secret (uses config default if None)
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not secret:
            secret = Config.WEBHOOK_SECRET
            
        if not secret:
            logger.warning("No webhook secret configured, skipping signature verification")
            return True
        
        if not signature:
            logger.warning("No signature provided in webhook request")
            return False
        
        try:
            # Agora also supports HMAC-SHA1
            expected_signature = hmac.new(
                secret.encode('utf-8'),
                payload,
                hashlib.sha1
            ).hexdigest()
            
            # Use constant-time comparison to prevent timing attacks
            is_valid = hmac.compare_digest(signature, expected_signature)
            
            if not is_valid:
                logger.warning(f"Invalid webhook signature (SHA1). Expected: {expected_signature}, Got: {signature}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature (SHA1): {e}")
            return False
    
    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str, secret: Optional[str] = None) -> bool:
        """
        Verify webhook signature, trying both SHA256 and SHA1 algorithms
        
        Args:
            payload: Raw webhook payload bytes
            signature: Signature from Agora-Signature header
            secret: Webhook secret (uses config default if None)
            
        Returns:
            True if signature is valid with either algorithm, False otherwise
        """
        # Try SHA256 first (preferred)
        if WebhookSecurity.verify_agora_signature(payload, signature, secret):
            return True
        
        # Fall back to SHA1
        if WebhookSecurity.verify_agora_signature_sha1(payload, signature, secret):
            return True
        
        return False
