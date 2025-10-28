#!/bin/bash

# Agora Webhooks Service Monitor
# This script monitors the service and restarts it if it's not responding

SERVICE_NAME="agora-webhooks"
HEALTH_URL="http://localhost:8080/health"
LOG_FILE="/home/ubuntu/frank/AgoraWebhooks/service_monitor.log"
MAX_RETRIES=3
RETRY_DELAY=10

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Function to check if service is running
check_service_running() {
    systemctl is-active --quiet "$SERVICE_NAME"
    return $?
}

# Function to check if service is responding to health checks
check_service_health() {
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null)
    if [ "$response" = "200" ]; then
        return 0
    else
        return 1
    fi
}

# Function to restart service
restart_service() {
    log_message "Restarting $SERVICE_NAME service..."
    sudo systemctl restart "$SERVICE_NAME"
    sleep 5
    
    if check_service_running; then
        log_message "Service restarted successfully"
        return 0
    else
        log_message "Failed to restart service"
        return 1
    fi
}

# Main monitoring logic
log_message "Starting service monitoring for $SERVICE_NAME"

retry_count=0
while true; do
    if check_service_running; then
        if check_service_health; then
            # Service is running and healthy
            if [ $retry_count -gt 0 ]; then
                log_message "Service is now healthy after $retry_count retries"
                retry_count=0
            fi
        else
            # Service is running but not responding to health checks
            log_message "Service is running but not responding to health checks"
            if [ $retry_count -lt $MAX_RETRIES ]; then
                retry_count=$((retry_count + 1))
                log_message "Attempting restart $retry_count/$MAX_RETRIES"
                if restart_service; then
                    sleep $RETRY_DELAY
                    continue
                else
                    log_message "Restart attempt $retry_count failed"
                fi
            else
                log_message "Max retries reached. Service may need manual intervention"
                retry_count=0
            fi
        fi
    else
        # Service is not running
        log_message "Service is not running"
        if [ $retry_count -lt $MAX_RETRIES ]; then
            retry_count=$((retry_count + 1))
            log_message "Attempting to start service $retry_count/$MAX_RETRIES"
            if restart_service; then
                sleep $RETRY_DELAY
                continue
            else
                log_message "Start attempt $retry_count failed"
            fi
        else
            log_message "Max retries reached. Service may need manual intervention"
            retry_count=0
        fi
    fi
    
    # Wait before next check
    sleep 30
done