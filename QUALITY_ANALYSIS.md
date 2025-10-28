# Quality Analysis System

This document describes the comprehensive quality analysis system used to evaluate call quality and user experience in the Agora Webhooks Dashboard.

## Overview

The quality analysis system uses Agora's reason codes from webhook events to assess call quality and provide actionable insights. Each reason code represents a specific type of user exit from a channel, and we categorize them by their impact on user experience.

## Reason Code Categories

### 🔴 High Impact Issues (Heavy Penalties)

These issues significantly impact user experience and should be prioritized for resolution.

#### Reason 999: Abnormal User
- **Description**: Users frequently joining/leaving channels in a short period
- **Quality Impact**: -15 points per event (max -60)
- **Suggested Actions**: 
  - Call the kick API to remove abnormal users
  - Implement rate limiting
  - Monitor for bot behavior
- **Tooltip**: "Users frequently joining/leaving (reason=999) - indicates abnormal user behavior, network issues, or connection problems"

#### Reason 0: Other Reasons
- **Description**: Unknown or unspecified reasons for leaving
- **Quality Impact**: -10 points per event (max -40)
- **Suggested Actions**: 
  - Investigate further
  - Check for edge cases
  - Monitor for patterns
- **Tooltip**: "Unknown issues (reason=0) - investigate further"

### 🟡 Medium Impact Issues (Moderate Penalties)

These issues indicate technical problems that affect call quality but may be temporary or user-specific.

#### Reason 2: Connection Timeout
- **Description**: Connection between client and Agora server timed out (>10 seconds without data)
- **Quality Impact**: -8 points per event (max -35)
- **Suggested Actions**: 
  - Check network stability
  - Monitor server response times
  - Implement connection retry logic
- **Tooltip**: "Connection timeouts (reason=2) - network instability"

#### Reason 10: Network Connection Problems
- **Description**: SDK didn't receive data packets for >4 seconds or socket connection error
- **Quality Impact**: -8 points per event (max -35)
- **Suggested Actions**: 
  - Check user network connectivity
  - Implement network quality monitoring
  - Provide network troubleshooting guidance
- **Tooltip**: "Network connection problems (reason=10) - check connectivity"

#### Reason 9: Multiple IP Addresses
- **Description**: Client has multiple IP addresses, SDK actively disconnects/reconnects
- **Quality Impact**: -8 points per event (max -35)
- **Suggested Actions**: 
  - Check for VPN usage
  - Monitor for multiple public IPs
  - Implement IP stability checks
- **Tooltip**: "IP switching events (reason=9) - VPN or multiple IPs detected"

#### Reason 4: Server Load Adjustment
- **Description**: Agora server adjusting load, temporarily disconnecting clients
- **Quality Impact**: -6 points per event (max -25)
- **Suggested Actions**: 
  - Monitor Agora server status
  - Implement automatic reconnection
  - Contact Agora support if frequent
- **Tooltip**: "Server load adjustments (reason=4) - Agora server issues"

### 🟢 Low Impact Issues (Light Penalties)

These issues are typically user-controlled or administrative actions that don't indicate technical problems.

#### Reason 3: Permissions Issue
- **Description**: Operator made user leave via RESTful API
- **Quality Impact**: -3 points per event (max -15)
- **Suggested Actions**: 
  - Review admin actions
  - Check permission policies
  - Monitor for abuse
- **Tooltip**: "Permission issues (reason=3) - admin actions"

#### Reason 5: Device Switch
- **Description**: User switched to new device, forcing old device offline
- **Quality Impact**: -3 points per event (max -15)
- **Suggested Actions**: 
  - Normal user behavior
  - No action required
  - Monitor for patterns
- **Tooltip**: "Device switches (reason=5) - user behavior"

### ✅ Good Indicators (Bonus)

These indicate positive user experience and normal behavior.

#### Reason 1: Normal Leave
- **Description**: User left channel normally
- **Quality Impact**: +5 points if >70% of exits are normal
- **Suggested Actions**: 
  - Maintain current setup
  - This is expected behavior
- **Tooltip**: "Normal exits (reason=1) - good user experience"

## Quality Score Calculation

### Base Score
- **Starting Score**: 100 points
- **Maximum Score**: 100 points
- **Minimum Score**: 0 points

### Penalty System
1. **High Impact Issues**: Apply heavy penalties first
2. **Medium Impact Issues**: Apply moderate penalties
3. **Low Impact Issues**: Apply light penalties
4. **Failed Calls**: -5 points per call <5 seconds (max -30)
5. **Short Sessions**: -20 points if average session <1 minute
6. **Good Exits Bonus**: +5 points if >70% exits are normal

### Quality Ranges
- **90-100**: 🟢 **Excellent Quality** - Minimal issues, great user experience
- **80-89**: 🟢 **Good Quality** - Some minor issues, generally good experience
- **50-79**: 🟡 **Moderate Quality** - Noticeable issues, needs attention
- **0-49**: 🔴 **Poor Quality** - Significant problems, immediate action required

## Additional Quality Metrics

### Failed Calls
- **Definition**: Sessions shorter than 5 seconds
- **Impact**: -5 points per failed call (max -30)
- **Tooltip**: "Sessions shorter than 5 seconds - likely failed connection attempts or technical issues"

### Session Length Analysis
- **Short Sessions**: Average <1 minute = -20 points
- **Histogram Categories**:
  - 0-5s: Failed connections
  - 5-30s: Quick disconnections
  - 30-60s: Brief sessions
  - 1-5min: Short sessions
  - 5-15min: Medium sessions
  - 15min+: Long sessions

### Test Channel Detection
- **Definition**: Channels with only 1 user
- **Impact**: Flagged as test channel
- **Tooltip**: "Test channel detected (only 1 user)"

## Per-User Quality Analysis

The system also provides comprehensive quality analysis on a per-user basis, allowing you to identify users with specific quality issues.

### User Quality Metrics

Each user gets their own quality score and detailed breakdown:

#### Quality Score Calculation (Per User)
- **Same scoring system** as channel-level analysis
- **Individual user behavior** analysis
- **Personalized insights** based on user's specific issues

#### User-Specific Data
- **Quality Score**: 0-100 for this specific user
- **Reason Breakdown**: Count of each reason code for this user
- **Failed Calls**: User's failed connection attempts
- **Churn Events**: User's abnormal behavior events
- **Reconnection Analysis**: Detailed analysis of user's reconnection patterns

### User Analytics Response

```json
{
  "users": [
    {
      "uid": 12345,
      "total_channels_joined": 3,
      "total_active_minutes": 45.2,
      "total_role_switches": 2,
      "platform_distribution": {"Android": 2, "iOS": 1},
      "failed_calls": 1,
      "churn_events": 0,
      "quality_score": 85.5,
      "reason_breakdown": {
        "good_exits": 5,
        "network_timeouts": 1,
        "permission_issues": 0,
        "server_issues": 0,
        "device_switches": 1,
        "ip_switching": 0,
        "network_issues": 0,
        "other_issues": 0
      },
      "reconnection_analysis": {
        "reconnection_count": 2,
        "burst_sessions": 0,
        "rapid_reconnections": 1,
        "avg_session_gap_minutes": 5.2,
        "reconnection_pattern": "moderate"
      }
    }
  ]
}
```

### Reconnection Pattern Analysis

The system analyzes user behavior patterns within the same call to identify connection issues:

#### Reconnection Metrics
- **Reconnection Count**: Total number of times user rejoined the same channel
- **Burst Sessions**: Sessions with gaps ≤ 30 seconds (rapid reconnections)
- **Rapid Reconnections**: Sessions with gaps ≤ 2 minutes
- **Average Session Gap**: Average time between leave and rejoin
- **Reconnection Pattern**: Overall stability assessment

#### Pattern Classifications
- **No Reconnections**: User joined once, left once (stable)
- **Stable**: Some reconnections but with reasonable gaps
- **Moderate**: Some rapid reconnections (1-2 within 2 minutes)
- **Unstable**: Frequent rapid reconnections (3+ within 2 minutes)

#### Quality Impact
- **Unstable Pattern**: -25 points (high penalty)
- **Moderate Pattern**: -15 points (medium penalty)
- **Any Rapid Reconnections**: -10 points (light penalty)
- **Burst Sessions**: -5 points per burst (max -20)

### User Quality Insights

The system can identify users with specific patterns:

#### High-Risk Users
- **Low quality scores** (< 50)
- **High churn events** (reason 999)
- **Multiple network issues** (reasons 2, 10)
- **Frequent failed calls**
- **Unstable reconnection patterns**

#### Good Users
- **High quality scores** (> 80)
- **Mostly normal exits** (reason 1)
- **Minimal technical issues**
- **Stable connections**
- **No reconnection issues**

#### Problematic Users
- **Abnormal behavior** (reason 999)
- **Network instability** (reasons 2, 10, 9)
- **Server issues** (reason 4)
- **Unknown problems** (reason 0)
- **Frequent reconnections** (burst patterns)

## Implementation Details

### Backend Processing
- **File**: `main.py` - `get_channel_quality_metrics()` and `get_channel_multi_user_analytics()` functions
- **Database**: Uses `ChannelSession` table with `reason` column
- **Caching**: Results cached for performance

### Frontend Display
- **File**: `templates/index.html`
- **Location**: Quality Metrics section and User Analytics
- **Features**: 
  - Color-coded insights
  - Detailed tooltips
  - Interactive quality scores
  - Per-user quality breakdowns

### API Endpoints
- **Channel Quality**: `GET /api/channel/{app_id}/{channel_name}/quality-metrics`
- **User Quality**: `GET /api/user/{app_id}/{uid}` (detailed user analytics)
- **Multi-User Quality**: `GET /api/channel/{app_id}/{channel_name}/users` (per-user breakdown)
- **Response Format**: JSON with quality score and insights

## Usage Examples

### Checking Channel Quality
```bash
curl https://your-domain.com/api/channel/your-app-id/channel-name/quality-metrics
```

### Response Example
```json
{
  "channel_name": "test-channel",
  "quality_score": 85.5,
  "insights": [
    "✅ 15 normal exits (reason=1) - good user experience",
    "🟡 2 connection timeouts (reason=2) - network instability",
    "📞 1 failed calls (duration < 5s)",
    "🟢 Good quality indicators"
  ],
  "churn_events": 0,
  "failed_calls": 1
}
```

## Best Practices

### Monitoring
1. **Set up alerts** for quality scores below 70
2. **Monitor trends** over time
3. **Track specific reason codes** that appear frequently
4. **Correlate with user complaints**

### Troubleshooting
1. **High churn events (999)**: Check for bot behavior or network issues
2. **Network timeouts (2, 10)**: Investigate user connectivity
3. **Server issues (4)**: Monitor Agora server status
4. **Unknown issues (0)**: Review logs for edge cases

### Optimization
1. **Implement retry logic** for network issues
2. **Add connection quality monitoring**
3. **Provide user guidance** for network problems
4. **Monitor and adjust** quality thresholds as needed

## Related Documentation

- [Main README](README.md) - Overall project documentation
- [API Documentation](README.md#-api-endpoints) - API endpoint details
- [Database Schema](README.md#-database-schema) - Database structure
- [Troubleshooting](README.md#-troubleshooting) - Common issues and solutions