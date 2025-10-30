#!/bin/bash
# Auto-fix emojis script - can be run manually or called by other scripts
# This ensures emojis are always fixed before important operations

cd "$(dirname "$0")"

if [ -f "fix_emojis.py" ]; then
    python3 fix_emojis.py
    exit $?
else
    echo "Error: fix_emojis.py not found"
    exit 1
fi
