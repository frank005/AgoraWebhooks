#!/bin/bash

# Agora Webhooks Server Deployment Script
# This script sets up the server on Ubuntu 24.04

set -e

echo "🚀 Starting Agora Webhooks Server deployment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   print_error "This script should not be run as root for security reasons"
   exit 1
fi

# Update system packages
print_status "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install Python 3.12 and pip (Ubuntu 24.04 default)
print_status "Installing Python 3.12 and pip..."
sudo apt install -y python3.12 python3.12-venv python3.12-dev python3-pip

# Install other required packages
print_status "Installing additional packages..."
sudo apt install -y nginx certbot python3-certbot-nginx ufw

# Create application directory
APP_DIR="/opt/agora-webhooks"
print_status "Creating application directory at $APP_DIR..."
sudo mkdir -p $APP_DIR
sudo chown $USER:$USER $APP_DIR

# Copy application files
print_status "Copying application files..."
cp -r . $APP_DIR/
cd $APP_DIR

# Fix emojis before deployment
print_status "Fixing emojis..."
if [ -f "fix_emojis.py" ]; then
    python3 fix_emojis.py || print_warning "Some emojis may need manual fixing"
fi

# Create virtual environment
print_status "Creating Python virtual environment..."
python3.12 -m venv venv
source venv/bin/activate

# Install Python dependencies
print_status "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Prompt for domain name (needed for .env and nginx config)
print_status "Please enter your domain name for SSL certificate setup"
read -p "Domain name (e.g., example.com): " DOMAIN_NAME
if [ -z "$DOMAIN_NAME" ]; then
    print_warning "No domain name provided. Using placeholder 'your-domain.com'"
    print_warning "You will need to update it manually later."
    DOMAIN_NAME="your-domain.com"
fi

# Create environment file
print_status "Creating environment configuration..."
cat > .env << EOF
# Database Configuration
DATABASE_URL=sqlite:///./agora_webhooks.db

# Server Configuration
HOST=0.0.0.0
PORT=8000
SSL_CERT_PATH=/etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/${DOMAIN_NAME}/privkey.pem

# Security (no authentication required)

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/agora-webhooks.log

# Background Processing
MAX_WORKERS=4
EOF

# Create systemd service file
print_status "Creating systemd service..."
sudo tee /etc/systemd/system/agora-webhooks.service > /dev/null << EOF
[Unit]
Description=Agora Webhooks Server
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
Environment=PATH=$APP_DIR/venv/bin
ExecStart=$APP_DIR/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create log directory and set permissions
print_status "Setting up logging..."
sudo mkdir -p /var/log
sudo touch /var/log/agora-webhooks.log
sudo chown $USER:$USER /var/log/agora-webhooks.log

# Configure firewall
print_status "Configuring firewall..."
sudo ufw --force enable
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Create nginx configuration
print_status "Creating nginx configuration..."
sudo tee /etc/nginx/sites-available/agora-webhooks > /dev/null << EOF
server {
    listen 80;
    server_name ${DOMAIN_NAME} www.${DOMAIN_NAME};
    
    # Redirect HTTP to HTTPS
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN_NAME} www.${DOMAIN_NAME};
    
    # SSL configuration (will be updated by certbot)
    ssl_certificate /etc/letsencrypt/live/${DOMAIN_NAME}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN_NAME}/privkey.pem;
    
    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # Proxy to FastAPI application
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # WebSocket support (if needed in future)
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

# Enable nginx site
sudo ln -sf /etc/nginx/sites-available/agora-webhooks /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx configuration
sudo nginx -t

# Prompt for certificate setup
print_status "SSL Certificate Setup"
print_warning "You need to obtain an SSL certificate for ${DOMAIN_NAME}"
read -p "Do you want to run certbot now to obtain a Let's Encrypt certificate? (y/N): " RUN_CERTBOT

if [ "$RUN_CERTBOT" = "y" ] || [ "$RUN_CERTBOT" = "Y" ]; then
    print_status "Running certbot to obtain SSL certificate..."
    print_warning "Make sure your domain ${DOMAIN_NAME} points to this server's IP address"
    read -p "Email address for Let's Encrypt notifications (optional): " CERTBOT_EMAIL
    
    if [ -z "$CERTBOT_EMAIL" ]; then
        CERTBOT_EMAIL="admin@${DOMAIN_NAME}"
    fi
    
    read -p "Press Enter to continue with certbot (or Ctrl+C to cancel)..."
    
    # Run certbot with nginx plugin
    if sudo certbot --nginx -d ${DOMAIN_NAME} -d www.${DOMAIN_NAME} --non-interactive --agree-tos --email ${CERTBOT_EMAIL} 2>/dev/null; then
        print_status "✅ SSL certificate obtained successfully"
        # Reload nginx after certbot
        sudo systemctl reload nginx
    else
        print_warning "⚠️  Certbot setup failed or requires interaction"
        print_warning "You can run it manually later with: sudo certbot --nginx -d ${DOMAIN_NAME}"
    fi
else
    print_warning "Skipping certificate setup. You can run it later with:"
    print_warning "  sudo certbot --nginx -d ${DOMAIN_NAME}"
fi

# Create monitoring script
print_status "Creating monitoring script..."
sudo tee /opt/agora-webhooks/monitor.sh > /dev/null << 'EOF'
#!/bin/bash

# Agora Webhooks Server Monitoring Script
# This script checks if the service is running and restarts it if needed

SERVICE_NAME="agora-webhooks"
HEALTH_URL="http://localhost:8000/health"
LOG_FILE="/var/log/agora-webhooks-monitor.log"

log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> $LOG_FILE
}

check_service() {
    if systemctl is-active --quiet $SERVICE_NAME; then
        return 0
    else
        return 1
    fi
}

check_service_health() {
    local response
    response=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null)
    if [ "$response" = "200" ]; then
        return 0
    else
        return 1
    fi
}

restart_service() {
    log_message "Service $SERVICE_NAME is not running or unhealthy. Attempting to restart..."
    systemctl restart $SERVICE_NAME
    sleep 5
    
    if check_service; then
        log_message "Service $SERVICE_NAME restarted successfully"
        return 0
    else
        log_message "Failed to restart service $SERVICE_NAME"
        return 1
    fi
}

# Check if service is running
if ! check_service; then
    restart_service
else
    # Service is running, check health endpoint
    if ! check_service_health; then
        log_message "Service is running but health check failed. Attempting restart..."
        restart_service
    else
        log_message "Service $SERVICE_NAME is running normally"
    fi
fi
EOF

sudo chmod +x /opt/agora-webhooks/monitor.sh

# Add cron job for monitoring
print_status "Setting up monitoring cron job..."
(crontab -l 2>/dev/null; echo "*/5 * * * * /opt/agora-webhooks/monitor.sh") | crontab -

# Reload systemd and start services
print_status "Starting services..."
sudo systemctl daemon-reload
sudo systemctl enable agora-webhooks
sudo systemctl start agora-webhooks
sudo systemctl restart nginx

# Check service status
sleep 5
if systemctl is-active --quiet agora-webhooks; then
    print_status "✅ Agora Webhooks service started successfully"
else
    print_error "❌ Failed to start Agora Webhooks service"
    sudo systemctl status agora-webhooks
    exit 1
fi

print_status "🎉 Deployment completed successfully!"
print_warning "⚠️  IMPORTANT: Next steps:"
print_warning "1. Domain configured: ${DOMAIN_NAME}"
if [ "$RUN_CERTBOT" != "y" ] && [ "$RUN_CERTBOT" != "Y" ]; then
    print_warning "2. Run SSL certificate setup: sudo certbot --nginx -d ${DOMAIN_NAME}"
fi
print_warning "3. Configure your Agora Console to send webhooks to: https://${DOMAIN_NAME}/{app_id}/webhooks"
print_warning "4. Update DNS records if needed to point ${DOMAIN_NAME} to this server"

echo ""
print_status "Service status:"
sudo systemctl status agora-webhooks --no-pager -l
echo ""
print_status "Logs:"
sudo journalctl -u agora-webhooks --no-pager -l -n 10
