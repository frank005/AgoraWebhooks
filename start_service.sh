#!/bin/bash
cd /home/ubuntu/frank/AgoraWebhooks
sudo pkill -f "python main.py"
sleep 2
sudo PORT=8080 ./venv/bin/python main.py &
echo "Service started on port 8080"