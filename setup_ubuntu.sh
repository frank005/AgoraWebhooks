#!/bin/bash

# Quick setup script for Ubuntu 24.04
# Run this if you're setting up manually without the full deploy.sh

set -e

echo "🚀 Setting up Agora Webhooks Server on Ubuntu 24.04..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Update system
print_status "Updating system packages..."
sudo apt update

# Install Python and required packages
print_status "Installing Python 3.12 and required packages..."
sudo apt install -y python3.12 python3.12-venv python3.12-dev python3-pip

# Install additional packages for production
print_status "Installing additional packages..."
sudo apt install -y nginx certbot python3-certbot-nginx ufw

# Create virtual environment
print_status "Creating Python virtual environment..."
python3.12 -m venv venv

# Activate virtual environment and install dependencies
print_status "Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    print_status "Creating .env file..."
    cat > .env << EOF
# Database Configuration
DATABASE_URL=sqlite:///./agora_webhooks.db

# Server Configuration
HOST=0.0.0.0
PORT=8000
SSL_CERT_PATH=
SSL_KEY_PATH=

# Security
SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
WEBHOOK_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')

# Logging
LOG_LEVEL=INFO
LOG_FILE=agora_webhooks.log

# Background Processing
MAX_WORKERS=4
EOF
fi

# Initialize database
print_status "Initializing database..."
python3 -c "from database import create_tables; create_tables()"

print_status "✅ Setup completed successfully!"
print_warning "⚠️  Next steps:"
print_warning "1. Activate virtual environment: source venv/bin/activate"
print_warning "2. Start development server: python start_dev.py"
print_warning "3. Or run full deployment: ./deploy.sh"
print_warning "4. Update WEBHOOK_SECRET in .env with your Agora webhook secret"

echo ""
print_status "🎉 Ready to go! Run 'source venv/bin/activate && python start_dev.py' to start"
