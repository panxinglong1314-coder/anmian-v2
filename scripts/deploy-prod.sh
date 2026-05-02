#!/bin/bash
set -e

PROJECT_DIR="/home/ubuntu/anmian"
SERVICE_NAME="anmian-backend.service"

cd $PROJECT_DIR

echo "[Deploy] Pulling latest code..."
git pull origin main

echo "[Deploy] Installing dependencies..."
source venv/bin/activate
pip install -r backend/requirements.txt -q

echo "[Deploy] Restarting service..."
sudo systemctl restart $SERVICE_NAME

echo "[Deploy] Done. Checking status..."
sleep 3
sudo systemctl status $SERVICE_NAME --no-pager

echo "[Deploy] ✅ Production deployment completed at $(date)"
