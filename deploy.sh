#!/bin/bash

# Agora Webhooks Server Deployment Script
# This script sets up the server on Ubuntu 24.04

set -e

echo "🚀 Starting Agora Webhooks Server deployment..."

# Rollback tracking variables
ROLLBACK_NEEDED=false
SERVICE_CREATED=false
NGINX_CONFIGURED=false
APP_DIR_CREATED=false
CRON_ADDED=false
FIREWALL_CONFIGURED=false

# Rollback function
rollback() {
    if [ "$ROLLBACK_NEEDED" = true ]; then
        print_error "❌ Deployment failed! Rolling back changes..."
        
        if [ "$SERVICE_CREATED" = true ]; then
            print_status "Stopping and removing service..."
            sudo systemctl stop agora-webhooks 2>/dev/null || true
            sudo systemctl disable agora-webhooks 2>/dev/null || true
            sudo rm -f /etc/systemd/system/agora-webhooks.service
            sudo systemctl daemon-reload
        fi
        
        if [ "$NGINX_CONFIGURED" = true ]; then
            print_status "Removing nginx configuration..."
            sudo rm -f /etc/nginx/sites-enabled/agora-webhooks
            sudo rm -f /etc/nginx/sites-available/agora-webhooks
            sudo systemctl reload nginx 2>/dev/null || true
        fi
        
        if [ "$CRON_ADDED" = true ]; then
            print_status "Removing cron job..."
            crontab -l 2>/dev/null | grep -v "$APP_DIR/monitor.sh" | crontab - 2>/dev/null || true
        fi
        
        # Don't remove the directory since it's the git repo
        print_warning "Application directory $APP_DIR (git repository) was not removed"
        
        print_error "Rollback complete. Please fix the errors and try again."
    fi
}

# Set trap for error handling
trap rollback ERR
trap 'ROLLBACK_NEEDED=true' EXIT

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

# Determine application directory (current directory where git repo is)
APP_DIR="$(pwd)"
print_status "Using application directory: $APP_DIR"
print_status "Make sure you're running this script from your git repository directory"

# Check if this looks like a git repository
if [ ! -d ".git" ]; then
    print_warning "Warning: .git directory not found. This might not be a git repository."
    print_warning "You won't be able to update with 'git pull' later."
fi

APP_DIR_CREATED=false  # We're not creating it, we're using existing

# Copy application files (exclude .git, venv, and other unnecessary files)
print_status "Copying application files..."
rsync -av --exclude='.git' --exclude='venv' --exclude='.env' --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' --exclude='*.log' --exclude='backups' --exclude='old' . $APP_DIR/ 2>/dev/null || {
    # Fallback to cp if rsync not available
    print_status "Using cp (rsync not available)..."
    find . -maxdepth 1 -not -name '.' -not -name '.git' -not -name 'venv' -not -name '.env' -not -name '__pycache__' -not -name 'backups' -not -name 'old' -exec cp -r {} $APP_DIR/ \;
}
cd $APP_DIR

# Fix emojis before deployment
print_status "Fixing emojis..."
if [ -f "fix_emojis.py" ]; then
    python3 fix_emojis.py || print_warning "Some emojis may need manual fixing"
fi

# Create virtual environment
print_status "Creating Python virtual environment..."
if [ -d "venv" ]; then
    print_warning "Virtual environment already exists. Removing it..."
    rm -rf venv
fi
python3.12 -m venv venv
source venv/bin/activate

# Install Python dependencies
print_status "Installing Python dependencies..."
pip install --upgrade pip
if ! pip install -r requirements.txt; then
    print_error "❌ Failed to install Python dependencies"
    print_error "Check requirements.txt and ensure all packages are available"
    exit 1
fi

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
LOG_FILE=$APP_DIR/agora-webhooks.log

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
Environment="PYTHONUNBUFFERED=1"
ExecStart=$APP_DIR/venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
SERVICE_CREATED=true

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
FIREWALL_CONFIGURED=true

# Warn about port 80 requirement
print_warning "⚠️  IMPORTANT: Port 80 must be open and accessible from the internet for Let's Encrypt certbot to work"
print_warning "   - The script configures UFW firewall (port 80 is now allowed)"
print_warning "   - You MUST also open port 80 in your cloud provider's security group/firewall"
print_warning "   - Certbot needs port 80 to validate domain ownership"

# Create nginx configuration (without SSL initially - certbot will add it)
print_status "Creating nginx configuration..."
sudo tee /etc/nginx/sites-available/agora-webhooks > /dev/null << EOF
server {
    listen 80;
    server_name ${DOMAIN_NAME} www.${DOMAIN_NAME};
    
    # Proxy to FastAPI application (HTTP only for now)
    # Certbot will modify this to redirect to HTTPS and add SSL server block
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
NGINX_CONFIGURED=true

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
    
    # Start nginx if not already running (needed for certbot)
    if ! systemctl is-active --quiet nginx; then
        print_status "Starting nginx..."
        sudo systemctl start nginx
        sleep 3  # Give nginx time to start
    else
        print_status "Reloading nginx..."
        sudo systemctl reload nginx
        sleep 2  # Give nginx time to reload
    fi
    
    # Check port 80 accessibility before running certbot
    print_status "Verifying port 80 is accessible..."
    
    # Wait a bit more for nginx to fully start
    sleep 2
    
    # Check if nginx is listening on port 80
    if ! (sudo netstat -tuln 2>/dev/null | grep -q ':80 ' || sudo ss -tuln 2>/dev/null | grep -q ':80 '); then
        print_error "❌ Port 80 is not listening!"
        print_error "   Nginx should be listening on port 80, but it's not."
        print_error ""
        print_error "   Please check:"
        print_error "   1. Port 80 is open in your cloud provider's security group/firewall"
        print_error "   2. Port 80 is allowed in UFW (should already be configured)"
        print_error "   3. Check nginx status: sudo systemctl status nginx"
        print_error "   4. Check nginx logs: sudo journalctl -u nginx -n 50"
        print_error ""
        print_error "   After fixing this, you can run certbot manually:"
        print_error "   sudo certbot --nginx -d ${DOMAIN_NAME}"
        exit 1
    fi
    
    # Check if UFW allows port 80
    if ! sudo ufw status | grep -q '80/tcp.*ALLOW'; then
        print_error "❌ Port 80 is not allowed in UFW firewall!"
        print_error "   Please run: sudo ufw allow 80/tcp"
        exit 1
    fi
    
    print_status "✅ Port 80 check passed"
    print_warning "   Note: Make sure port 80 is also open in your cloud provider's firewall/security group"
    
    # Run certbot with nginx plugin (don't suppress errors)
    print_status "Running certbot (this may take 30-60 seconds)..."
    if sudo certbot --nginx -d ${DOMAIN_NAME} -d www.${DOMAIN_NAME} --non-interactive --agree-tos --email ${CERTBOT_EMAIL}; then
        print_status "✅ SSL certificate obtained successfully"
        # Reload nginx after certbot
        sudo systemctl reload nginx
    else
        print_error "❌ Certbot failed!"
        print_error "   Common issues:"
        print_error "   1. Port 80 not accessible from internet (check cloud provider firewall)"
        print_error "   2. Domain DNS not pointing to this server"
        print_error "   3. Rate limiting from Let's Encrypt (too many certificate requests)"
        print_error ""
        print_error "   You can run certbot manually with:"
        print_error "   sudo certbot --nginx -d ${DOMAIN_NAME}"
        # Don't exit here - allow deployment to continue without SSL
        print_warning "⚠️  Continuing deployment without SSL certificate..."
    fi
else
    print_warning "Skipping certificate setup. You can run it later with:"
    print_warning "  sudo certbot --nginx -d ${DOMAIN_NAME}"
fi

# Create monitoring script
print_status "Creating monitoring script..."
tee $APP_DIR/monitor.sh > /dev/null << 'EOF'
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

sudo chmod +x $APP_DIR/monitor.sh

# Add cron job for monitoring
print_status "Setting up monitoring cron job..."
(crontab -l 2>/dev/null; echo "*/5 * * * * $APP_DIR/monitor.sh") | crontab -
CRON_ADDED=true

# Reload systemd and start services
print_status "Starting services..."

# Ensure templates directory exists
print_status "Ensuring templates directory exists..."
mkdir -p $APP_DIR/templates

# Test that the application can start
print_status "Testing application startup..."
if $APP_DIR/venv/bin/python -c "from database import create_tables; create_tables(); print('Database OK')" 2>&1; then
    print_status "✅ Database initialization test passed"
else
    print_error "❌ Database initialization failed!"
    print_error "This might prevent the service from starting."
fi

# Ensure log file exists and has correct permissions
touch $APP_DIR/agora-webhooks.log 2>/dev/null || true

# Ensure database directory is writable
print_status "Ensuring database directory is writable..."
sudo -u $USER touch $APP_DIR/agora_webhooks.db.test 2>/dev/null && rm -f $APP_DIR/agora_webhooks.db.test || {
    print_error "❌ Cannot write to $APP_DIR - fixing permissions..."
    sudo chown -R $USER:$USER $APP_DIR
    sudo chmod -R u+w $APP_DIR
}

# Ensure .env file permissions
chmod 644 $APP_DIR/.env 2>/dev/null || true

sudo systemctl daemon-reload
sudo systemctl enable agora-webhooks
sudo systemctl start agora-webhooks
sudo systemctl restart nginx || sudo systemctl start nginx

# Disable rollback on success - everything worked!
ROLLBACK_NEEDED=false
trap - ERR EXIT

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
