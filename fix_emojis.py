#!/usr/bin/env python3
"""
Fix all broken emojis in the codebase.

This script fixes UTF-8 encoding issues that corrupt emojis to '??' or '?'.
Run this script whenever emojis get broken.

Usage:
    python3 fix_emojis.py
"""

import re
import sys
import os

def fix_all_emojis():
    """Fix all broken emojis in main.py and templates/index.html"""
    
    # Fix main.py
    if not os.path.exists('main.py'):
        print("Error: main.py not found")
        return False
    
    with open('main.py', 'r', encoding='utf-8') as f:
        py_content = f.read()
    
    py_fixes = [
        # Quality insights
        (r'quality_insights\.append\(f"(\?|\?\?) User {uid}', r'quality_insights.append(f"🔴 User {uid}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {other_issues}', r'quality_insights.append(f"🔴 {other_issues}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {network_timeouts}', r'quality_insights.append(f"🟡 {network_timeouts}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {network_issues}', r'quality_insights.append(f"🟡 {network_issues}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {ip_switching}', r'quality_insights.append(f"🟡 {ip_switching}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {server_issues}', r'quality_insights.append(f"🟡 {server_issues}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {permission_issues}', r'quality_insights.append(f"🟢 {permission_issues}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {device_switches}', r'quality_insights.append(f"🟢 {device_switches}'),
        (r'quality_insights\.append\(f"\? {good_exits}', r'quality_insights.append(f"✅ {good_exits}'),
        (r'quality_insights\.append\(f"(\?|\?\?) {failed_calls}', r'quality_insights.append(f"📞 {failed_calls}'),
        (r'quality_insights\.append\(f"(\?|\?\?) High role switching', r'quality_insights.append(f"🔄 High role switching'),
        (r'quality_insights\.append\(f"(\?|\?\?) Short average session length', r'quality_insights.append(f"⏱️ Short average session length'),
        # Insights
        (r'insights\.append\(f"(\?|\?\?) {churn_events}', r'insights.append(f"🔴 {churn_events}'),
        (r'insights\.append\(f"(\?|\?\?) {other_issues}', r'insights.append(f"🔴 {other_issues}'),
        (r'insights\.append\(f"(\?|\?\?) {network_timeouts}', r'insights.append(f"🟡 {network_timeouts}'),
        (r'insights\.append\(f"(\?|\?\?) {network_issues}', r'insights.append(f"🟡 {network_issues}'),
        (r'insights\.append\(f"(\?|\?\?) {ip_switching}', r'insights.append(f"🟡 {ip_switching}'),
        (r'insights\.append\(f"(\?|\?\?) {server_issues}', r'insights.append(f"🟡 {server_issues}'),
        (r'insights\.append\(f"(\?|\?\?) {permission_issues}', r'insights.append(f"🟢 {permission_issues}'),
        (r'insights\.append\(f"(\?|\?\?) {device_switches}', r'insights.append(f"🟢 {device_switches}'),
        (r'insights\.append\(f"\? {good_exits}', r'insights.append(f"✅ {good_exits}'),
        (r'insights\.append\(f"(\?|\?\?) {failed_calls}', r'insights.append(f"📞 {failed_calls}'),
        (r'insights\.append\("(\?|\?\?) Test channel', r'insights.append("🧪 Test channel'),
        (r'insights\.append\(f"(\?|\?\?) Short average session length', r'insights.append(f"⏱️ Short average session length'),
        (r'insights\.append\("(\?|\?\?) Poor quality', r'insights.append("🔴 Poor quality'),
        (r'insights\.append\("(\?|\?\?) Moderate quality', r'insights.append("🟡 Moderate quality'),
        (r'insights\.append\("(\?|\?\?) Good quality', r'insights.append("🟢 Good quality'),
    ]
    
    py_fixed_count = 0
    for pattern, replacement in py_fixes:
        matches = len(re.findall(pattern, py_content))
        py_content = re.sub(pattern, replacement, py_content)
        if matches > 0:
            py_fixed_count += matches
    
    # Additional direct string replacements for quality insights (more reliable than regex)
    # These handle cases where emojis might be partially broken or encoded differently
    direct_fixes = [
        ('quality_insights.append(f"?? User', 'quality_insights.append(f"🔴 User'),
        ('quality_insights.append(f"?? {other_issues}', 'quality_insights.append(f"🔴 {other_issues}'),
        ('quality_insights.append(f"?? {network_timeouts}', 'quality_insights.append(f"🟡 {network_timeouts}'),
        ('quality_insights.append(f"?? {network_issues}', 'quality_insights.append(f"🟡 {network_issues}'),
        ('quality_insights.append(f"?? {ip_switching}', 'quality_insights.append(f"🟡 {ip_switching}'),
        ('quality_insights.append(f"?? {server_issues}', 'quality_insights.append(f"🟡 {server_issues}'),
        ('quality_insights.append(f"?? {permission_issues}', 'quality_insights.append(f"🟢 {permission_issues}'),
        ('quality_insights.append(f"?? {device_switches}', 'quality_insights.append(f"🟢 {device_switches}'),
        ('quality_insights.append(f"? {good_exits}', 'quality_insights.append(f"✅ {good_exits}'),
        ('quality_insights.append(f"?? {failed_calls}', 'quality_insights.append(f"📞 {failed_calls}'),
        ('quality_insights.append(f"?? High role switching', 'quality_insights.append(f"🔄 High role switching'),
        ('quality_insights.append(f"?? Short average session length', 'quality_insights.append(f"⏱️ Short average session length'),
        ('insights.append(f"?? {churn_events}', 'insights.append(f"🔴 {churn_events}'),
        ('insights.append(f"?? {other_issues}', 'insights.append(f"🔴 {other_issues}'),
        ('insights.append(f"?? {network_timeouts}', 'insights.append(f"🟡 {network_timeouts}'),
        ('insights.append(f"?? {network_issues}', 'insights.append(f"🟡 {network_issues}'),
        ('insights.append(f"?? {ip_switching}', 'insights.append(f"🟡 {ip_switching}'),
        ('insights.append(f"?? {server_issues}', 'insights.append(f"🟡 {server_issues}'),
        ('insights.append(f"?? {permission_issues}', 'insights.append(f"🟢 {permission_issues}'),
        ('insights.append(f"?? {device_switches}', 'insights.append(f"🟢 {device_switches}'),
        ('insights.append(f"? {good_exits}', 'insights.append(f"✅ {good_exits}'),
        ('insights.append(f"?? {failed_calls}', 'insights.append(f"📞 {failed_calls}'),
        ('insights.append("?? Test channel', 'insights.append("🧪 Test channel'),
        ('insights.append(f"?? Short average session length', 'insights.append(f"⏱️ Short average session length'),
        ('insights.append("?? Poor quality', 'insights.append("🔴 Poor quality'),
        ('insights.append("?? Moderate quality', 'insights.append("🟡 Moderate quality'),
        ('insights.append("?? Good quality', 'insights.append("🟢 Good quality'),
    ]
    
    for old, new in direct_fixes:
        if old in py_content:
            py_content = py_content.replace(old, new)
            py_fixed_count += py_content.count(new) - py_content.count(old) if new in py_content else 1
    
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(py_content)
    
    print(f"Fixed {py_fixed_count} emojis in main.py")
    
    # Fix templates/index.html
    html_path = 'templates/index.html'
    if not os.path.exists(html_path):
        print(f"Warning: {html_path} not found")
        return py_fixed_count > 0
    
    with open(html_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    html_fixes = [
        # Flag mappings - handle whitespace variations
        (r"text:\s*'(\?|\?\?) Local Recording'", "text: '📹 Local Recording'"),
        (r"text:\s*'(\?|\?\?) Applets'", "text: '📱 Applets'"),
        (r"text:\s*'(\?|\?\?) Cloud Recording'", "text: '☁️ Cloud Recording'"),
        (r"text:\s*'(\?|\?\?) Media Pull'", "text: '⬇️ Media Pull'"),
        (r"text:\s*'(\?|\?\?) Media Push'", "text: '⬆️ Media Push'"),
        (r"text:\s*'(\?|\?\?) Media Relay'", "text: '🔄 Media Relay'"),
        (r"text:\s*'(\?|\?\?) STT PubBot'", "text: '🎤 STT PubBot'"),
        (r"text:\s*'(\?|\?\?) STT SubBot'", "text: '🎧 STT SubBot'"),
        (r"text:\s*'(\?|\?\?) Media Gateway'", "text: '🌐 Media Gateway'"),
        (r"text:\s*'(\?|\?\?) Conversational AI'", "text: '🤖 Conversational AI'"),
        (r"text:\s*'(\?|\?\?\?) Real-Time STT'", "text: '🎙️ Real-Time STT'"),
        # Buttons and labels - handle whitespace
        (r"textContent\s*=\s*'(\?|\?\?) Share Link'", "textContent = '📋 Share Link'"),
        (r'">\s*(\?|\?\?)\s*Role Analytics<', '">👥 Role Analytics<'),
        (r'">\s*(\?|\?\?)\s*Quality Metrics<', '">📊 Quality Metrics<'),
        (r'">\s*(\?|\?\?\?\?)\s*Multi-User View<', '">👥👥 Multi-User View<'),
        # Icons in comments
        (r"//\s*Mic icon\s*\((\?|\?\?)\)", "// Mic icon (🎤)"),
        (r"//\s*Ear icon\s*\((\?|\?\?)\)", "// Ear icon (👂)"),
        # Icon variables - handle all variations (more comprehensive patterns)
        (r"const\s+finalIcon\s*=\s*isHost\s*\?\s*'🎤'\s*:\s*'(\?|\?\?)'", "const finalIcon = isHost ? '🎤' : '👂'"),
        (r"const\s+finalIcon\s*=\s*isHost\s*\?\s*'(\?|\?\?)'\s*:\s*'(\?|\?\?)'", "const finalIcon = isHost ? '🎤' : '👂'"),
        (r"const\s+initialIcon\s*=\s*isHost\s*\?\s*'👂'\s*:\s*'(\?|\?\?)'", "const initialIcon = isHost ? '👂' : '🎤'"),
        (r"const\s+initialIcon\s*=\s*isHost\s*\?\s*'(\?|\?\?)'\s*:\s*'(\?|\?\?)'", "const initialIcon = isHost ? '👂' : '🎤'"),
        (r"const\s+icon\s*=\s*isHost\s*\?\s*'(\?|\?\?)'\s*:\s*'(\?|\?\?)'", "const icon = isHost ? '🎤' : '👂'"),
        # Fix "Many Series Detected" warning
        (r"<strong>(\?\?)\s*Many Series Detected:", "<strong>⚠️ Many Series Detected:"),
        # Fix comment with broken emojis - handle partial fixes
        (r"// Mic icon \((\?\?)\) for Host, Ear icon \((\?\?)\) for Audience", "// Mic icon (🎤) for Host, Ear icon (👂) for Audience"),
        (r"// Mic icon \(🎤\) for Host, Ear icon \((\?\?)\) for Audience", "// Mic icon (🎤) for Host, Ear icon (👂) for Audience"),
        (r"// Mic icon \((\?\?)\) for Host, Ear icon \(👂\) for Audience", "// Mic icon (🎤) for Host, Ear icon (👂) for Audience"),
        # Active Filters text
        (r"<strong>(\?\?)\s*Active Filters:", "<strong>🔄 Active Filters:"),
        # Headers
        (r"<h4>(\?|\?\?)\s*Panel", "<h4>👤 Panel"),
        (r"<h3>(\?|\?\?)\s*Overview</h3>", "<h3>📊 Overview</h3>"),
        (r"<h3>(\?|\?\?)\s*Platform Distribution</h3>", "<h3>📱 Platform Distribution</h3>"),
        (r"<h3>(\?|\?\?)\s*Product Usage</h3>", "<h3>🔧 Product Usage</h3>"),
        (r"<h3>(\?|\?\?)\s*Quality Metrics</h3>", "<h3>📊 Quality Metrics</h3>"),
        (r"<h3>(\?|\?\?)\s*Channels List</h3>", "<h3>📋 Channels List</h3>"),
        (r"<h3>(\?|\?\?)\s*Quality Insights</h3>", "<h3>⚠️ Quality Insights</h3>"),
        (r"<h3>(\?|\?\?)\s*Role Breakdown</h3>", "<h3>👥 Role Breakdown</h3>"),
        (r"<h3>(\?|\?\?)\s*Platform Usage</h3>", "<h3>📱 Platform Usage</h3>"),
        (r"<h3>(\?|\?\?)\s*Quality Overview</h3>", "<h3>📊 Quality Overview</h3>"),
        (r"<h3>(\?|\?\?)\s*Concurrent Users Over Time</h3>", "<h3>📈 Concurrent Users Over Time</h3>"),
        (r"<h3>(\?|\?\?)\s*Session Length Distribution</h3>", "<h3>📈 Session Length Distribution</h3>"),
        # Buttons - fix arrows
        (r">(\?|\?\?)\s*Previous</button>", ">← Previous</button>"),
        (r"Next\s*(\?|\?\?)</button>", "Next →</button>"),
        (r">(\?|\?\?)\s*Back to Channels</button>", ">← Back to Channels</button>"),
        (r"Jump to Top\">(\?|\?\?)", "Jump to Top\">↑"),
        # Analytics buttons
        (r">(\?\?|:'\(|\\?\\?)\\s*Role Analytics</button>", r">👥 Role Analytics</button>"),
        (r">(\?\?|\\?\\?)\\s*Quality Metrics</button>", r">📊 Quality Metrics</button>"),
        (r">(\?\?\?\?|\\?\\?\\?\\?)\\s*Multi-User View</button>", r">👥👥 Multi-User View</button>"),
        (r"title=\"View Analytics\">\s*📊\?", r"title=\"View Analytics\">\n                                            📊"),
        # Analytics button
        (r'onclick="showUserAnalytics\(\$\{session\.uid\}\)"[^>]*>\s*(\?|\?\?)', r'onclick="showUserAnalytics(${session.uid})" style="padding: 2px 6px; font-size: 0.7rem; background: linear-gradient(135deg, #6f42c1, #e83e8c);" title="View Analytics">\n                                            📊'),
        # Role switch emojis - microphone and ear
        (r"isHost \? 'M-pM-\^_M-\^NM-\$' : 'M-pM-\^_M-\^QM-\^B'", r"isHost ? '🎤' : '👂'"),
        (r"isHost \? 'M-pM-\^_M-\^QM-\^B' : 'M-pM-\^_M-\^NM-\$'", r"isHost ? '👂' : '🎤'"),
        # Role transition arrow
        (r'<span style="font-size: 0\.7em; color: #666;">(\?|\?\?)</span>', r'<span style="font-size: 0.7em; color: #666;">→</span>'),
        # Date formatting bullet - SIMPLE pattern catch bullet + spaces + + anywhere
        (r'•\s{2,}\+\s*dateStr', r"• ' + dateStr"),
        # Date formatting bullet - handle missing quote before + (MOST COMMON - catch this FIRST)
        (r"peakTimeDisplay\s*=\s*'<span[^>]*>(?:•|M-bM-\^@M-\")\s{2,}\+\s*dateStr", r"peakTimeDisplay = '<span style=\"font-size: 0.75em; color: #999; margin-left: 8px; font-weight: normal;\">• ' + dateStr"),
        (r"peakTimeDisplay\s*=\s*'<span[^>]*>\?\s{2,}\+\s*dateStr", r"peakTimeDisplay = '<span style=\"font-size: 0.75em; color: #999; margin-left: 8px; font-weight: normal;\">• ' + dateStr"),
        (r"peakTimeDisplay\s*=\s*'<span[^>]*>(\?|\?\?)\s*\+\s*dateStr", r"peakTimeDisplay = '<span style=\"font-size: 0.75em; color: #999; margin-left: 8px; font-weight: normal;\">• ' + dateStr"),
        (r"peakTimeDisplay\s*=\s*'<span[^>]*>•\s{2,}\+", r"peakTimeDisplay = '<span style=\"font-size: 0.75em; color: #999; margin-left: 8px; font-weight: normal;\">• ' +"),
        (r"peakTimeDisplay\s*=\s*'<span[^>]*>(\?|\?\?)\s*'", r"peakTimeDisplay = '<span style=\"font-size: 0.75em; color: #999; margin-left: 8px; font-weight: normal;\">• '"),
    ]
    
    html_fixed_count = 0
    for pattern, replacement in html_fixes:
        matches = len(re.findall(pattern, html_content))
        html_content = re.sub(pattern, replacement, html_content)
        if matches > 0:
            html_fixed_count += matches
    
    # Additional direct fixes for patterns that are hard to regex (inside template literals)
    before_count = html_content.count("const finalIcon = isHost ? '??' : '??';")
    html_content = html_content.replace("const finalIcon = isHost ? '??' : '??';", "const finalIcon = isHost ? '🎤' : '👂';")
    html_content = html_content.replace("const finalIcon = isHost ? '??' : '??';", "const finalIcon = isHost ? '🎤' : '👂';")
    html_content = html_content.replace("const initialIcon = isHost ? '??' : '??';", "const initialIcon = isHost ? '👂' : '🎤';")
    html_content = html_content.replace("const icon = isHost ? '??' : '??';", "const icon = isHost ? '🎤' : '👂';")
    
    # Fix flag mappings directly
    html_content = html_content.replace("text: '?? Local Recording'", "text: '📹 Local Recording'")
    html_content = html_content.replace("text: '?? Applets'", "text: '📱 Applets'")
    html_content = html_content.replace("text: '?? Cloud Recording'", "text: '☁️ Cloud Recording'")
    html_content = html_content.replace("text: '?? Media Pull'", "text: '⬇️ Media Pull'")
    html_content = html_content.replace("text: '?? Media Push'", "text: '⬆️ Media Push'")
    html_content = html_content.replace("text: '?? Media Relay'", "text: '🔄 Media Relay'")
    html_content = html_content.replace("text: '?? STT PubBot'", "text: '🎤 STT PubBot'")
    html_content = html_content.replace("text: '?? STT SubBot'", "text: '🎧 STT SubBot'")
    html_content = html_content.replace("text: '?? Media Gateway'", "text: '🌐 Media Gateway'")
    html_content = html_content.replace("text: '?? Conversational AI'", "text: '🤖 Conversational AI'")
    html_content = html_content.replace("text: '??? Real-Time STT'", "text: '🎙️ Real-Time STT'")
    
    # Fix "Many Series Detected" warning - handle both with and without spaces
    html_content = html_content.replace("<strong>?? Many Series Detected:", "<strong>⚠️ Many Series Detected:")
    html_content = html_content.replace('">?? Role Analytics', '">👥 Role Analytics')
    html_content = html_content.replace('">?? Quality Metrics', '">📊 Quality Metrics')
    html_content = html_content.replace('">???? Multi-User View', '">👥👥 Multi-User View')
    html_content = html_content.replace("textContent = '?? Share Link'", "textContent = '📋 Share Link'")
    html_content = html_content.replace("// Mic icon (??) for Host, Ear icon (??) for Audience", "// Mic icon (🎤) for Host, Ear icon (👂) for Audience")
    html_content = html_content.replace("// Mic icon (🎤) for Host, Ear icon (??) for Audience", "// Mic icon (🎤) for Host, Ear icon (👂) for Audience")
    html_content = html_content.replace("// Mic icon (??) for Host, Ear icon (👂) for Audience", "// Mic icon (🎤) for Host, Ear icon (👂) for Audience")
    html_content = html_content.replace("<strong>?? Active Filters:", "<strong>🔄 Active Filters:")
    html_content = html_content.replace("<h4>?? Panel", "<h4>👤 Panel")
    html_content = html_content.replace("<h3>?? Overview</h3>", "<h3>📊 Overview</h3>")
    html_content = html_content.replace("<h3>?? Platform Distribution</h3>", "<h3>📱 Platform Distribution</h3>")
    html_content = html_content.replace("<h3>?? Product Usage</h3>", "<h3>🔧 Product Usage</h3>")
    html_content = html_content.replace("<h3>?? Quality Metrics</h3>", "<h3>📊 Quality Metrics</h3>")
    html_content = html_content.replace("<h3>?? Channels List</h3>", "<h3>📋 Channels List</h3>")
    html_content = html_content.replace("<h3>?? Quality Insights</h3>", "<h3>⚠️ Quality Insights</h3>")
    html_content = html_content.replace("<h3>?? Role Breakdown</h3>", "<h3>👥 Role Breakdown</h3>")
    html_content = html_content.replace("<h3>?? Platform Usage</h3>", "<h3>📱 Platform Usage</h3>")
    html_content = html_content.replace("<h3>?? Quality Overview</h3>", "<h3>📊 Quality Overview</h3>")
    html_content = html_content.replace("<h3>?? Concurrent Users Over Time</h3>", "<h3>📈 Concurrent Users Over Time</h3>")
    html_content = html_content.replace("<h3>?? Session Length Distribution</h3>", "<h3>📈 Session Length Distribution</h3>")
    html_content = html_content.replace("const finalIcon = isHost ? '??' : '??';", "const finalIcon = isHost ? '🎤' : '👂';")
    html_content = html_content.replace("const initialIcon = isHost ? '??' : '??';", "const initialIcon = isHost ? '👂' : '🎤';")
    html_content = html_content.replace("const icon = isHost ? '??' : '??';", "const icon = isHost ? '🎤' : '👂';")
    # Fix any remaining ?? after emojis
    html_content = html_content.replace("📊??", "📊")
    
    # Count how many we fixed
    after_final = html_content.count("const finalIcon = isHost ? '🎤' : '👂';")
    after_initial = html_content.count("const initialIcon = isHost ? '👂' : '🎤';")
    after_icon = html_content.count("const icon = isHost ? '🎤' : '👂';")
    if before_count > 0:
        html_fixed_count += before_count
    
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Fixed {html_fixed_count} emojis in {html_path}")
    
    return True


def verify_emojis():
    """Verify that emojis are fixed correctly"""
    files = {
        'main.py': ['🔴', '🟡', '🟢', '✅', '📞', '🔄', '⏱️'],
        'templates/index.html': ['📊', '👥', '📱', '🔧', '📋', '⚠️', '📈', '👤', '📹', '☁️', '⬇️', '⬆️', '🎤', '🎧', '🌐', '🤖', '🎙️', '🧪', '←', '→', '↑']
    }
    
    all_good = True
    for filepath, expected_emojis in files.items():
        if not os.path.exists(filepath):
            continue
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count broken emojis - only look for actual broken patterns
        # Count ?? patterns (these are definitely broken)
        broken = content.count('??')
        # Don't count ? as broken unless it's clearly part of a broken emoji pattern
        # JavaScript ternary operators use '? ' which is not a broken emoji
        working = sum(1 for emoji in expected_emojis if emoji in content)
        
        if broken > 0:
            print(f"⚠️  {filepath}: {broken} broken emoji(s) remaining")
            all_good = False
        else:
            print(f"✅ {filepath}: {working} working emojis, 0 broken")
    
    return all_good


if __name__ == '__main__':
    print("🔧 Fixing all broken emojis...")
    print("-" * 50)
    
    if fix_all_emojis():
        print("-" * 50)
        print("✅ Emoji fix complete!")
        print("\nVerifying fixes...")
        print("-" * 50)
        
        if verify_emojis():
            print("-" * 50)
            print("✅ All emojis are fixed!")
            sys.exit(0)
        else:
            print("-" * 50)
            print("⚠️  Some emojis may still be broken. Please check manually.")
            sys.exit(1)
    else:
        print("-" * 50)
        print("❌ Failed to fix emojis")
        sys.exit(1)
