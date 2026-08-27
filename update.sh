#!/usr/bin/env bash
# =============================================================================
# cMPLiBe AIScanner - 1-Click Update Script for Hostinger VPS
# =============================================================================

set -e

echo "🚀 [1/3] Pulling latest updates from GitHub main branch..."
cd /var/www/cmplibe-job-scanner
git pull origin main

echo "📦 [2/3] Checking dependencies..."
source venv/bin/activate
pip install -r requirements.txt --quiet

echo "🔄 [3/3] Restarting 24/7 background scanner service..."
systemctl restart cmplibe-jobs

echo "=========================================================="
echo "✅ cMPLiBe AIScanner updated successfully!"
echo "• Status: $(systemctl is-active cmplibe-jobs)"
echo "• Live at: https://www.cmplibe.com/job-scanner"
echo "=========================================================="
