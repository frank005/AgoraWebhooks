#!/bin/bash

# macOS Startup Script for Agora Webhooks Server
# This script sets up and starts the server for local development

set -e

echo "🍎 Starting Agora Webhooks Server on macOS..."

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Check if we're in a virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    print_warning "Not in a virtual environment. Creating one..."
    
    # Create virtual environment if it doesn't exist
    if [ ! -d "venv" ]; then
        print_status "Creating Python virtual environment..."
        python3 -m venv venv
    fi
    
    # Activate virtual environment
    print_status "Activating virtual environment..."
    source venv/bin/activate
else
    print_status "Virtual environment already active: $VIRTUAL_ENV"
fi

# Check if requirements are installed
print_status "Checking dependencies..."
if ! python -c "import fastapi, uvicorn, sqlalchemy" 2>/dev/null; then
    print_status "Installing dependencies..."
    
    # Try to install with pre-compiled wheels first
    print_status "Attempting to install with pre-compiled wheels..."
    if pip install -r requirements-macos.txt; then
        print_status "✅ Dependencies installed successfully"
    else
        print_warning "Failed to install with pre-compiled wheels, trying alternative approach..."
        
        # Try installing without building from source
        print_status "Installing without building from source..."
        pip install --only-binary=all -r requirements.txt || {
            print_warning "Still failing, trying with older pydantic version..."
            pip install --only-binary=all fastapi uvicorn sqlalchemy alembic python-multipart jinja2 python-dotenv pydantic==1.10.13 asyncio-mqtt apscheduler
        }
    fi
else
    print_status "Dependencies already installed"
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    print_status "Creating .env file for local development..."
    cat > .env << EOF
# Local Development Configuration
DATABASE_URL=sqlite:///./agora_webhooks.db
HOST=127.0.0.1
PORT=8000
SSL_CERT_PATH=
SSL_KEY_PATH=
LOG_LEVEL=DEBUG
LOG_FILE=agora_webhooks.log
MAX_WORKERS=2
EOF
    print_status "✅ Created .env file"
else
    print_status "✅ .env file already exists"
fi

# Initialize database
print_status "Initializing database..."
python -c "from database import create_tables; create_tables()"

# Start the server
print_status "🚀 Starting development server..."
print_info "Server will be available at: http://127.0.0.1:8000"
print_info "Web interface: http://127.0.0.1:8000/"
print_info "Health check: http://127.0.0.1:8000/health"
print_info "Press Ctrl+C to stop"
print_info ""
print_info "To expose publicly, run in another terminal:"
print_info "  ngrok http 8000"
print_info ""
print_info "Then use the ngrok URL for webhook endpoints:"
print_info "  https://your-ngrok-url.ngrok.io/{app_id}/webhooks"
echo ""

# Start the server
python start_dev.py
