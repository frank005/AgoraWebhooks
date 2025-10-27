"""
Mapping utilities for Agora webhook values
"""

# Platform mappings from Agora documentation
PLATFORM_MAPPING = {
    0: "Other",
    1: "Android",
    2: "iOS", 
    5: "Windows",
    6: "Linux",
    7: "Web",
    8: "macOS"
}

# Product ID mappings
PRODUCT_ID_MAPPING = {
    1: "Realtime Communication (RTC)",
    3: "Cloud Recording", 
    4: "Media Pull",
    5: "Media Push"
}

# Client Type mappings (only for Linux platform)
CLIENT_TYPE_MAPPING = {
    3: "Local server recording",
    8: "Applets", 
    10: "Cloud recording"
}

def get_platform_name(platform_id, client_type=None):
    """Get platform name from platform ID, optionally with client type for Linux"""
    if platform_id is None:
        return "N/A"
    
    platform_name = PLATFORM_MAPPING.get(platform_id, str(platform_id))
    
    # If it's Linux (6) and we have a client type, append it
    if platform_id == 6 and client_type is not None:
        client_name = CLIENT_TYPE_MAPPING.get(client_type, str(client_type))
        return f"{platform_name} ({client_name})"
    
    return platform_name

def get_product_name(product_id):
    """Get product name from product ID"""
    if product_id is None:
        return "N/A"
    return PRODUCT_ID_MAPPING.get(product_id, str(product_id))

def log_unknown_values(platform_id, product_id, event_type, channel_name):
    """Log unknown platform/product ID values for future mapping"""
    import logging
    logger = logging.getLogger(__name__)
    
    if platform_id and platform_id not in PLATFORM_MAPPING:
        logger.warning(f"Unknown platform ID: {platform_id} for event {event_type} in channel {channel_name}")
    
    if product_id and product_id not in PRODUCT_ID_MAPPING:
        logger.warning(f"Unknown product ID: {product_id} for event {event_type} in channel {channel_name}")