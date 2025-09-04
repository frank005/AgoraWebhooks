# Agora Webhooks Server

A Python-based webhook server for receiving and processing Agora video calling notifications. This server provides real-time analytics and monitoring for your Agora applications.

## Features

- **Webhook Reception**: Receives Agora webhooks via HTTPS POST requests with route-based App ID handling
- **Real-time Processing**: Processes webhook events and calculates usage metrics
- **Web Dashboard**: Beautiful web interface for viewing channel analytics and user statistics
- **Security**: HMAC signature verification for webhook authenticity
- **Database Storage**: SQLite database for storing webhook events and calculated metrics
- **Monitoring**: Built-in health checks and monitoring scripts
- **Production Ready**: Systemd service, nginx reverse proxy, SSL support

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Agora Cloud   │───▶│  Webhook Server  │───▶│   SQLite DB     │
│                 │    │   (FastAPI)      │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │  Web Dashboard   │
                       │   (HTML/JS)      │
                       └──────────────────┘
```

## Quick Start

### 1. Clone and Setup

```bash
git clone <your-repo-url>
cd AgoraWebhooks
```

### 2. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment

Copy and edit the configuration:

```bash
cp config.py .env
# Edit .env with your settings
```

### 4. Run Locally (Development)

```bash
python main.py
```

The server will start on `http://localhost:8000`

### 5. Deploy to Production

Run the deployment script on your Ubuntu 24.04 server:

```bash
./deploy.sh
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLite database path | `sqlite:///./agora_webhooks.db` |
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `443` |
| `SSL_CERT_PATH` | SSL certificate path | None |
| `SSL_KEY_PATH` | SSL private key path | None |
| `SECRET_KEY` | Application secret key | Auto-generated |
| `WEBHOOK_SECRET` | Agora webhook secret | Auto-generated |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FILE` | Log file path | `agora_webhooks.log` |

### Agora Console Setup

1. Log in to [Agora Console](https://console.agora.io)
2. Navigate to your project
3. Go to **All Features** → **Notifications**
4. Configure:
   - **Event**: Select events you want to monitor (e.g., User joined/left channel)
   - **Receiving Server URL Endpoint**: `https://your-domain.com/{app_id}/webhooks`
   - **Whitelist**: Add your server's IP addresses

## API Endpoints

### Webhook Endpoint

```
POST /{app_id}/webhooks
```

Receives Agora webhook notifications for the specified App ID.

**Headers:**
- `Agora-Signature`: HMAC signature for verification
- `Content-Type`: `application/json`

**Example:**
```bash
curl -X POST https://your-domain.com/your-app-id/webhooks \
  -H "Content-Type: application/json" \
  -H "Agora-Signature: your-signature" \
  -d '{
    "noticeId": "12345",
    "productId": 1,
    "eventType": 1,
    "payload": {
      "clientSeq": 67890,
      "uid": 123,
      "channelName": "test_channel",
      "ts": 1560496834
    }
  }'
```

### API Endpoints

- `GET /api/channels/{app_id}` - Get list of channels for an App ID
- `GET /api/channel/{app_id}/{channel_name}` - Get detailed channel information
- `GET /api/user/{app_id}/{uid}` - Get user metrics
- `GET /health` - Health check endpoint

### Web Interface

- `GET /` - Main dashboard interface

## Database Schema

### Tables

1. **webhook_events** - Raw webhook events from Agora
2. **channel_sessions** - Calculated user sessions with join/leave times
3. **channel_metrics** - Aggregated metrics per channel per day
4. **user_metrics** - Aggregated metrics per user per channel per day

## Monitoring

### Service Status

```bash
sudo systemctl status agora-webhooks
```

### View Logs

```bash
# Service logs
sudo journalctl -u agora-webhooks -f

# Application logs
tail -f /var/log/agora-webhooks.log

# Monitor script logs
tail -f /var/log/agora-webhooks-monitor.log
```

### Health Check

```bash
curl https://your-domain.com/health
```

## Security

- **HMAC Signature Verification**: All webhooks are verified using HMAC-SHA256
- **HTTPS Only**: Production deployment uses SSL/TLS encryption
- **Security Headers**: Nginx configured with security headers
- **Firewall**: UFW configured to allow only necessary ports

## Troubleshooting

### Common Issues

1. **Service won't start**
   ```bash
   sudo systemctl status agora-webhooks
   sudo journalctl -u agora-webhooks -n 50
   ```

2. **Webhook signature verification fails**
   - Check `WEBHOOK_SECRET` in `.env` matches Agora Console
   - Verify webhook payload format

3. **Database issues**
   ```bash
   # Check database file permissions
   ls -la agora_webhooks.db
   
   # Reset database (WARNING: deletes all data)
   rm agora_webhooks.db
   python -c "from database import create_tables; create_tables()"
   ```

4. **SSL certificate issues**
   ```bash
   # Renew Let's Encrypt certificate
   sudo certbot renew
   sudo systemctl reload nginx
   ```

## Development

### Project Structure

```
AgoraWebhooks/
├── main.py              # FastAPI application
├── config.py            # Configuration management
├── database.py          # Database models and setup
├── models.py            # Pydantic models
├── webhook_processor.py # Webhook processing logic
├── security.py          # Security utilities
├── templates/           # HTML templates
│   └── index.html      # Web dashboard
├── requirements.txt     # Python dependencies
├── deploy.sh           # Deployment script
└── README.md           # This file
```

### Adding New Features

1. **New Webhook Events**: Update `webhook_processor.py` to handle new event types
2. **New Metrics**: Add new tables in `database.py` and update processing logic
3. **New API Endpoints**: Add routes in `main.py`
4. **UI Changes**: Modify `templates/index.html`

## License

This project is licensed under the MIT License.

## Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs
3. Create an issue in the repository
