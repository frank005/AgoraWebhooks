#!/usr/bin/env python3
"""
Development startup script for Agora Webhooks Server
This script sets up the development environment and starts the server.
"""

import os
import sys
import subprocess
from pathlib import Path

def main():
    """Start the development server"""
    
    # Check if we're in a virtual environment
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("⚠️  Warning: Not running in a virtual environment")
        print("   Consider running: python3 -m venv venv && source venv/bin/activate")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    # Check if requirements are installed
    try:
        import fastapi
        import uvicorn
        import sqlalchemy
        print("✅ Required packages are installed")
    except ImportError as e:
        print(f"❌ Missing required package: {e}")
        print("   Run: pip install -r requirements.txt")
        sys.exit(1)
    
    # Create .env file if it doesn't exist
    env_file = Path(".env")
    if not env_file.exists():
        print("📝 Creating .env file for development...")
        env_content = """# Development Configuration
DATABASE_URL=sqlite:///./agora_webhooks.db
HOST=127.0.0.1
PORT=8000
SSL_CERT_PATH=
SSL_KEY_PATH=
LOG_LEVEL=DEBUG
LOG_FILE=agora_webhooks.log
MAX_WORKERS=2
"""
        env_file.write_text(env_content)
        print("✅ Created .env file")
    else:
        print("✅ .env file already exists")
    
    # Create templates directory if it doesn't exist
    templates_dir = Path("templates")
    if not templates_dir.exists():
        print("📁 Creating templates directory...")
        templates_dir.mkdir()
    
    # Initialize database
    print("🗄️  Initializing database...")
    try:
        from database import create_tables
        create_tables()
        print("✅ Database initialized")
    except Exception as e:
        print(f"❌ Failed to initialize database: {e}")
        sys.exit(1)
    
    # Start the server
    print("🚀 Starting development server...")
    print("   Server will be available at: http://127.0.0.1:8000")
    print("   Web interface: http://127.0.0.1:8000/")
    print("   Health check: http://127.0.0.1:8000/health")
    print("   Press Ctrl+C to stop")
    print("-" * 50)
    
    try:
        # Start the server using uvicorn command
        import uvicorn
        
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
    except Exception as e:
        print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
