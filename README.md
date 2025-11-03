# Agora Webhooks Server

A comprehensive Python-based webhook server for receiving and processing Agora video calling notifications. This server provides real-time analytics, monitoring, and a beautiful web dashboard for your Agora applications.

## ✨ Features

### Core Functionality
- **Webhook Reception**: Receives Agora webhooks via HTTPS POST requests with route-based App ID handling
- **Real-time Processing**: Processes webhook events and calculates usage metrics with intelligent session tracking
- **Duplicate Prevention**: Advanced in-memory and database-based duplicate webhook detection
- **Session Management**: Automatic channel session tracking with join/leave event correlation
- **Smart Caching**: In-memory caching for performance optimization

### Web Dashboard
- **Beautiful UI**: Modern, responsive web interface with gradient design
- **Real-time Analytics**: Live channel statistics and user metrics
- **Interactive Search**: Search channels by name with pagination
- **Advanced Filtering**: Filter channels by date, platform, client type, and role with URL persistence
- **Detailed Views**: Comprehensive channel and user session details
- **Mobile Responsive**: Works perfectly on desktop and mobile devices
- **Shareable Links**: Permalink functionality for sharing specific channels with team members
- **Visual Channel Flags**: Color-coded indicators showing client types (Cloud Recording, Media Push/Pull, Conversational AI, etc.)
- **Role Analytics**: Track host vs audience minutes with role switching detection
- **Concurrent Users Graph**: Visualize concurrent users over time for each channel session
- **Role Indicators**: Visual mic/ear icons showing user roles (🎤 Host, 👂 Audience) with stacked indicators for role switches
- **Chart Drill-Down**: Click data points in Minutes Analytics to filter channels automatically

### Data Management
- **SQLite Database**: Lightweight, file-based database for easy deployment
- **Comprehensive Metrics**: Track total minutes, unique users, session counts
- **Platform Detection**: Automatic platform identification (Android, iOS, Web, etc.)
- **Product Mapping**: Support for RTC, Cloud Recording, Media Push/Pull
- **Historical Data**: Store and analyze historical webhook events

### Production Ready
- **SSL/TLS Support**: Full HTTPS encryption for production deployments
- **Systemd Integration**: Service management with automatic startup
- **Nginx Reverse Proxy**: Production-grade web server configuration
- **Health Monitoring**: Built-in health checks and monitoring endpoints
- **Logging**: Comprehensive logging with configurable levels
- **Security**: Firewall configuration and security headers

## 🏗️ Architecture

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

## 🚀 Quick Start

### 1. Clone and Setup

```bash
git clone https://github.com/frank005/AgoraWebhooks.git
cd AgoraWebhooks
```

### 2. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment

Create your environment configuration:

```bash
cp env.example .env
# Edit .env with your settings
```

### 4. Run Locally (Development)

```bash
python start_dev.py
```

The server will start on `http://localhost:8000`

### 5. Deploy to Production

**Prerequisites:**
- Ubuntu 24.04 server
- Sudo access
- Domain name pointing to your server's IP address
- **Port 80 must be open** in your cloud provider's firewall/security group (required for Let's Encrypt certbot)
  - The script configures UFW firewall, but you must also open port 80 in your cloud provider's security group/firewall
  - Certbot needs port 80 to validate domain ownership

Run the deployment script on your Ubuntu 24.04 server:

```bash
./deploy.sh
```

The script will:
- Install all dependencies (Python, nginx, certbot, etc.)
- Prompt for your domain name
- Configure the firewall (ports 22, 80, 443)
- Set up SSL certificates via Let's Encrypt (optional)
- Configure and start the service

**Important:** Before running certbot, ensure port 80 is open in your cloud provider's firewall/security group. Certbot needs port 80 to validate domain ownership.

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLite database path | `sqlite:///./agora_webhooks.db` |
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `443` |
| `SSL_CERT_PATH` | SSL certificate path | None |
| `SSL_KEY_PATH` | SSL private key path | None |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FILE` | Log file path | `agora_webhooks.log` |
| `MAX_WORKERS` | Background processing workers | `4` |

### Agora Console Setup

1. Log in to [Agora Console](https://console.agora.io)
2. Navigate to your project
3. Go to **All Features** → **Notifications**
4. Configure:
   - **Event**: Select events you want to monitor (e.g., User joined/left channel)
   - **Receiving Server URL Endpoint**: `https://your-domain.com/{app_id}/webhooks`
   - **Whitelist**: Add your server's IP addresses

## 📡 API Endpoints

### Webhook Endpoint

```
POST /{app_id}/webhooks
```

Receives Agora webhook notifications for the specified App ID.

**Headers:**
- `Content-Type`: `application/json`

**Example:**
```bash
curl -X POST https://your-domain.com/your-app-id/webhooks \
  -H "Content-Type: application/json" \
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

- `GET /api/channels/{app_id}` - Get list of channels for an App ID with pagination and optional filters
  - **Query Parameters:**
    - `page` (int, default: 1) - Page number for pagination
    - `per_page` (int, default: 30) - Number of results per page
    - `start_date` (string, optional) - Filter by start date (ISO format: `YYYY-MM-DDTHH:MM:SSZ`)
    - `end_date` (string, optional) - Filter by end date (ISO format: `YYYY-MM-DDTHH:MM:SSZ`)
    - `platform` (int, optional) - Filter by platform ID (1=Android, 2=iOS, 5=Windows, 6=Linux, 7=Web, 8=macOS)
    - `client_type` (int, optional) - Filter by client type (e.g., 10=Cloud Recording, 28=Media Pull, 30=Media Push, 60=Conversational AI, -1=NULL)
    - `role` (string, optional) - Filter by role (`"host"` or `"audience"`)
- `GET /api/channel/{app_id}/{channel_name}` - Get detailed channel information with role-split metrics
- `GET /api/channel/{app_id}/{channel_name}/role-analytics` - Get role and product analytics with wall clock time
- `GET /api/channel/{app_id}/{channel_name}/quality-metrics` - Get quality metrics with concurrent users graph data
- `GET /api/user/{app_id}/{uid}` - Get user metrics and session history
- `GET /api/user/{app_id}/{uid}/detailed` - Get detailed user analytics including SID, quality insights, and platform distribution
- `GET /health` - Health check endpoint
- `GET /debug/cache` - Debug cache status

### Web Interface

- `GET /` - Main dashboard interface with search and analytics
- `GET /?appId={app_id}&channel={channel_name}&sessionId={session_id}` - Direct channel view with permalink support
- `GET /?appId={app_id}&filterDate={date}&filterPlatform={platform}&filterClientType={client_type}&filterRole={role}` - Channels list with filters

## 🔍 Filtering System

The dashboard supports comprehensive filtering to help you analyze your Agora channel data efficiently. Filters can be applied in multiple ways and persist in the URL for easy bookmarking and sharing.

### Available Filters

#### 1. **Date Filter** (`filterDate`)
- **Format**: `YYYY-MM-DD` (e.g., `2025-11-01`)
- **Purpose**: Filter channels to show only sessions that occurred on a specific date
- **Usage**: When filtering by date, the system shows channels that have sessions overlapping with the specified date
- **Example**: `?appId=your-app-id&filterDate=2025-11-01`

#### 2. **Platform Filter** (`filterPlatform`)
- **Values**: Platform ID numbers
  - `1` - Android
  - `2` - iOS
  - `5` - Windows
  - `6` - Linux
  - `7` - Web
  - `8` - macOS
- **Purpose**: Filter channels to show only sessions from a specific platform
- **Example**: `?appId=your-app-id&filterPlatform=7` (Web only)

#### 3. **Client Type Filter** (`filterClientType`)
- **Values**: Client type ID numbers or `-1` for NULL
  - `3` - Local Recording
  - `8` - Applets
  - `10` - Cloud Recording
  - `28` - Media Pull
  - `30` - Media Push
  - `43` - Media Relay
  - `47` - STT PubBot
  - `48` - STT SubBot
  - `50` - Media Gateway
  - `60` - Conversational AI
  - `68` - Real-Time STT
  - `-1` - NULL (no client type specified)
- **Purpose**: Filter channels to show only sessions using a specific client type
- **Example**: `?appId=your-app-id&filterClientType=10` (Cloud Recording only)
- **Special Case**: Use `-1` to filter for sessions with NULL client type (typically Linux platform sessions)

#### 4. **Role Filter** (`filterRole`)
- **Values**: `"host"` or `"audience"`
- **Purpose**: Filter channels to show only sessions for users with a specific role
  - `host` - Shows only host/broadcaster sessions
  - `audience` - Shows only audience/listener sessions
- **Example**: `?appId=your-app-id&filterRole=host`
- **Note**: If both roles are selected in the minutes analytics chart, no role filter is applied (shows all roles)

### How Filters Work

#### Applying Filters

1. **Via URL Parameters**: Add filter parameters directly to the URL
   ```
   https://your-domain.com/?appId=your-app-id&filterDate=2025-11-01&filterPlatform=7&filterRole=host
   ```

2. **Via Chart Drill-Down**: Click on any data point in the Minutes Analytics chart
   - The system automatically extracts filters from the clicked data point
   - Navigates to the channels list with filters applied
   - URL is updated with all relevant filter parameters

3. **Filter Combinations**: Multiple filters can be combined
   - Filters work together (AND logic)
   - Example: `filterDate=2025-11-01&filterPlatform=7&filterRole=host` shows only Web host sessions on Nov 1, 2025

#### Filter Indicator

When filters are active, a blue banner appears at the top of the channels list showing:
- **Active Filters**: Lists all currently applied filters
- **Clear Filters Button**: One-click removal of all filters

Example display:
```
🔄 Active Filters: Date: 2025-11-01 | Platform: 7 | Client Type: 10 | Role: host  [Clear Filters]
```

#### Filter Persistence

- **URL Preservation**: All filters are stored in the URL query parameters
- **Bookmarkable**: You can bookmark filtered views for quick access
- **Shareable**: Share filtered URLs with team members
- **Auto-Restoration**: When navigating between pages, filters are automatically preserved

#### Special Behaviors

1. **Role Filter Logic**:
   - When filtering from the minutes analytics chart:
     - If **one role** was selected in the chart → role filter is applied
     - If **both roles** were selected → no role filter (shows all roles)
   - This ensures that clicking a data point when viewing all roles doesn't restrict the results

2. **Date Filter Behavior**:
   - Single date filter (`filterDate`) filters for sessions that overlap with that date
   - When both `start_date` and `end_date` are the same, it filters for that single day
   - Sessions are included if they overlap with the date range, even if they started before or ended after

3. **Client Type NULL Handling**:
   - Use `filterClientType=-1` to filter for sessions with NULL client type
   - Commonly seen in Linux platform sessions where client type may not be specified

### Filter Examples

**Example 1: Filter by Date**
```
?appId=your-app-id&filterDate=2025-11-01
```
Shows all channels with sessions on November 1, 2025.

**Example 2: Filter by Platform and Role**
```
?appId=your-app-id&filterPlatform=7&filterRole=host
```
Shows only Web platform host sessions.

**Example 3: Filter by Date, Platform, and Client Type**
```
?appId=your-app-id&filterDate=2025-11-01&filterPlatform=6&filterClientType=-1
```
Shows Linux platform sessions with NULL client type on November 1, 2025.

**Example 4: Complex Filter Combination**
```
?appId=your-app-id&filterDate=2025-11-01&filterPlatform=7&filterClientType=10&filterRole=host
```
Shows Web platform Cloud Recording host sessions on November 1, 2025.

### Clearing Filters

- **Clear Filters Button**: Click the "Clear Filters" button in the filter indicator banner
- **Manual Removal**: Remove filter parameters from the URL
- **New Search**: Start a new search without filters

## 🗄️ Database Schema

### Tables

1. **webhook_events** - Raw webhook events from Agora
   - Stores all incoming webhook data with timestamps
   - Includes platform, product, and event type information

2. **channel_sessions** - Calculated user sessions with join/leave times
   - Tracks individual user sessions within channels
   - Calculates session duration and tracks completion status

3. **channel_metrics** - Aggregated metrics per channel per day
   - Daily summaries of channel activity
   - Total minutes, unique users, and session counts

4. **user_metrics** - Aggregated metrics per user per channel per day
   - User-specific analytics and usage patterns
   - Cross-channel user activity tracking

## 🔍 Advanced Features

### Filtering System
- **Comprehensive Filters**: Filter channels by date, platform, client type, and role
- **URL-Based Filtering**: All filters persist in URL for bookmarking and sharing
- **Chart Drill-Down**: Click data points in Minutes Analytics to filter channels
- **Filter Combinations**: Combine multiple filters for precise analysis
- **Filter Indicator**: Visual banner showing active filters with one-click clear
- See the [Filtering System](#-filtering-system) section for detailed documentation

### Permalink Functionality
- **Shareable URLs**: Direct links to specific channels and sessions
- **URL Parameters**: Support for `?appId={app_id}&channel={channel_name}&sessionId={session_id}`
- **Filter Support**: Permalinks include filter parameters for filtered views
- **Auto-navigation**: Automatically loads specified channels when visiting permalinks
- **Share Button**: One-click URL copying with visual feedback
- **Browser History**: Proper URL updates without page reloads

### Role and Communication Mode Indicators
- **Role Flags**: Visual indicators showing user roles and communication modes
- **Supported Combinations**:
  - 🔴 **RTC/Host** - Real-time communication host (communication_mode=1, is_host=true)
  - 🟡 **ILS/Host** - Interactive live streaming host (communication_mode=0, is_host=true)
  - 🔵 **ILS/Audience** - Interactive live streaming audience (communication_mode=0, is_host=false)
- **Event Type Mapping**:
  - Events 103/104: Broadcaster Join/Leave → ILS/Host
  - Events 105/106: Audience Join/Leave → ILS/Audience
  - Events 107/108: Communication Join/Leave → RTC/Host
  - Events 111/112: Role Change → Tracks role switches (broadcaster ↔ audience)
- **Smart Session Assignment**: Correctly assigns users to channel sessions even when leave events arrive after channel destroy events
- **Role Indicators**: Visual icons in session tables:
  - 🎤 **Mic icon** (purple circle) = Host/Broadcaster
  - 👂 **Ear icon** (blue circle) = Audience/Listener
  - **Stacked icons** = Role switch detected (bottom = initial role, top = final role)
- **Role-Split Metrics**: Separate tracking of host minutes, audience minutes, unique hosts, and unique audiences

### Visual Channel Flags
- **Client Type Indicators**: Color-coded flags showing what types of clients were used
- **Supported Types**:
  - ☁️ **Cloud Recording** (red) - Client type 10
  - ⬇️ **Media Pull** (blue) - Client type 28
  - ⬆️ **Media Push** (green) - Client type 30
  - 🤖 **Conversational AI** (purple) - Client type 60
  - 🔄 **Media Relay** (orange) - Client type 43
  - 🎤 **STT PubBot** (teal) - Client type 47
  - 🎧 **STT SubBot** (teal) - Client type 48
  - 🎙️ **Real-Time STT** (teal) - Client type 68
  - 🌐 **Media Gateway** (gray) - Client type 50
  - 📹 **Local Recording** (yellow) - Client type 3
  - 📱 **Applets** (pink) - Client type 8
- **Raw Numeric Values**: Platform and Product ID display includes raw numeric values in muted text (e.g., "Web (7)", "RTC (1)") to avoid mapping errors

### Duplicate Prevention
- **In-memory caching**: Fast detection of recent duplicate webhooks
- **Database verification**: Comprehensive duplicate checking against historical data
- **Configurable cache size**: Adjustable cache size for different deployment scenarios

### Session Tracking
- **Automatic correlation**: Links join and leave events to create complete sessions
- **Duration calculation**: Accurate session duration tracking
- **Platform detection**: Identifies user platforms (Android, iOS, Web, etc.)
- **Product mapping**: Supports RTC, Cloud Recording, Media Push/Pull

### Performance Optimization
- **Async processing**: Non-blocking webhook processing
- **Smart caching**: In-memory caches for frequently accessed data
- **Efficient queries**: Optimized database queries with proper indexing
- **Background processing**: Separate worker processes for heavy operations

## 📊 Monitoring

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

### Debug Information

```bash
curl https://your-domain.com/debug/cache
```

## 🔒 Security

- **HTTPS Only**: Production deployment uses SSL/TLS encryption
- **Security Headers**: Nginx configured with security headers
- **Firewall**: UFW configured to allow only necessary ports
- **No Signature Verification**: Webhooks are accepted without signature validation for simplified operation
- **Input Validation**: Comprehensive webhook payload validation

## 🛠️ Troubleshooting

### Common Issues

1. **Service won't start**
   ```bash
   sudo systemctl status agora-webhooks
   sudo journalctl -u agora-webhooks -n 50
   ```

2. **Webhook processing fails**
   - Check webhook payload format matches expected structure
   - Verify App ID in URL path is valid
   - Review logs for specific error messages

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

5. **Performance issues**
   - Check cache hit rates in debug endpoint
   - Monitor database query performance
   - Review background worker status

## 🧪 Development

### Project Structure

```
AgoraWebhooks/
├── main.py              # FastAPI application
├── config.py            # Configuration management
├── database.py          # Database models and setup
├── models.py            # Pydantic models
├── webhook_processor.py # Webhook processing logic
├── mappings.py          # Platform and product mappings
├── fix_emojis.py       # Utility script to fix broken emojis
├── templates/           # HTML templates
│   └── index.html      # Web dashboard
├── old/                 # Archived files and tests
│   └── tests/          # Test scripts
├── requirements.txt     # Python dependencies
├── deploy.sh           # Deployment script
├── start_dev.py        # Development startup script
└── README.md           # This file
```

### Utility Scripts

**fix_emojis.py** - Fixes UTF-8 encoding issues that corrupt emojis to '??' or '?'
- **Automatically runs before git commits** (via pre-commit hook)
- **Automatically runs after git pull/merge** (via post-merge hook)
- **Automatically runs during deployment** (via deploy.sh)
- Run manually if needed: `python3 fix_emojis.py`
- Automatically fixes all emojis in `main.py` and `templates/index.html`
- Includes verification to ensure all emojis are properly restored
- **Enhanced Protection**: The script now handles partial emoji corruption and edge cases

**Emoji Protection System**:
- ✅ **Git Hooks**: Pre-commit and post-merge hooks automatically fix emojis
- ✅ **EditorConfig**: `.editorconfig` file ensures UTF-8 encoding for all editors
- ✅ **Deploy Script**: Deployment automatically fixes emojis before deploying
- ✅ **Manual Fix**: Run `python3 fix_emojis.py` anytime to fix broken emojis

**Note**: Emojis may get corrupted when files are edited through certain tools that don't preserve UTF-8 encoding properly. The git hooks and EditorConfig file help prevent this, but if you notice broken emojis, simply run `python3 fix_emojis.py` to fix them automatically.

### Adding New Features

1. **New Webhook Events**: Update `webhook_processor.py` to handle new event types
2. **New Metrics**: Add new tables in `database.py` and update processing logic
3. **New API Endpoints**: Add routes in `main.py`
4. **UI Changes**: Modify `templates/index.html`
5. **Platform Support**: Update `mappings.py` for new platforms or products

### Testing

Test scripts are available in the `old/tests/` directory:
- `test_webhook.py` - Basic webhook testing
- `test_complete_session.py` - Session simulation
- `test_duplicate_prevention.py` - Duplicate detection testing

## 📈 Performance

### Benchmarks
- **Webhook Processing**: < 50ms average response time
- **Database Queries**: Optimized with proper indexing
- **Memory Usage**: < 100MB typical usage
- **Concurrent Users**: Supports 1000+ concurrent webhook requests

### Optimization Tips
- Use SSD storage for database files
- Configure appropriate cache sizes based on traffic
- Monitor memory usage and adjust worker counts
- Regular database maintenance and cleanup

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

For issues and questions:
1. Check the troubleshooting section
2. Review the logs
3. Create an issue in the repository
4. Check the `old/tests/` directory for test examples

## 🔄 Changelog

### Recent Updates
- ✅ **Fixed Date and Client Type Filters**: Resolved issue where date and client_type filters were not working correctly
  - Fixed SQLite datetime comparison by converting timezone-aware datetimes to naive UTC format
  - Fixed client_type parameter parsing to ensure proper integer conversion
  - Added comprehensive debug logging for filter troubleshooting
  - Filters now work correctly for date ranges and client type filtering
  - **Important**: Service restart required after code changes for filters to take effect
- ✅ **Enhanced Emoji Fix Script**: Improved `fix_emojis.py` with comprehensive pattern matching
  - Now handles all emoji patterns including template literals, flag mappings, analytics buttons, and section headers
  - Added direct string replacements for reliable emoji restoration
  - Fixed all broken emojis across the application (flag mappings, analytics buttons, role icons, section headers)
  - Script now automatically fixes 40+ emoji patterns reliably
- ✅ **Emoji Fixes**: Fixed all broken emojis across the application
  - Fixed emojis in role quality view, multi-user view, and quality insights
  - Fixed analytics buttons (Role Analytics, Quality Metrics, Multi-User View)
  - Fixed user analytics button and Jump to Top button
  - Fixed flag mappings (Local Recording, Applets, Cloud Recording, Media Pull/Push, etc.)
  - Fixed all section headers (Overview, Platform Distribution, Quality Metrics, etc.)
  - Fixed role icons (🎤 for Host, 👂 for Audience)
  - All emojis now display correctly throughout the dashboard
- ✅ **Session ID (SID) Support**: Added Agora session ID tracking and display in user analytics
  - SID extracted from webhook payloads and stored in database
  - Displayed in User Analytics title with small grey text formatting (matching date display style)
  - Populated from historical webhook logs for existing sessions
- ✅ **Emoji Fix Script**: Created `fix_emojis.py` utility script to fix UTF-8 encoding issues that corrupt emojis
  - Run `python3 fix_emojis.py` whenever emojis get broken
  - Automatically fixes all emojis in `main.py` and `templates/index.html`
  - Includes verification to ensure all emojis are properly restored
- ✅ **Role and Communication Mode Indicators**: Added visual indicators to distinguish between different communication modes and roles (RTC/Host, ILS/Host, ILS/Audience)
- ✅ **Fixed Channel Session Assignment**: Resolved issue where users were incorrectly assigned to different channel sessions when leave events came after channel destroy events
- ✅ **Enhanced Session Tracking**: Improved logic to correctly match leave events to their corresponding channel sessions using timestamp-based correlation
- ✅ **Communication Mode Support**: Added support for tracking communication mode (RTC vs ILS) in session data and API responses
- ✅ **Role Flag Display**: Frontend now displays short role indicators (RTC/Host, ILS/Host, ILS/Audience) for better user understanding
- ✅ **Permalink Functionality**: Share specific channels with team members via direct URLs
- ✅ **Visual Channel Flags**: Color-coded indicators for different client types (Cloud Recording, Media Push/Pull, Conversational AI, etc.)
- ✅ **Enhanced Channel Display**: Improved channel cards with client type information and visual indicators
- ✅ **Share Button**: One-click URL copying for easy channel sharing
- ✅ Repository cleanup and organization
- ✅ Advanced duplicate prevention system
- ✅ Improved session tracking and correlation
- ✅ Enhanced web dashboard with modern UI
- ✅ Platform and product mapping system
- ✅ Performance optimizations and caching
- ✅ Comprehensive logging and monitoring
- ✅ Production deployment improvements