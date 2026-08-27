#!/usr/bin/env bash
# =============================================================================
# cMPLiBe AIScanner - Hostinger VPS 1-Click Deployment Script
# Target: https://www.cmplibe.com/job-scanner
# =============================================================================

set -e

echo "=========================================================="
echo "  🐝 cMPLiBe AIScanner - Automated Hostinger VPS Deployer"
echo "=========================================================="

APP_DIR="/var/www/cmplibe-job-scanner"
SERVICE_NAME="cmplibe-jobs"

# 1. Detect Package Manager & Install Prerequisites
if command -v apt-get >/dev/null 2>&1; then
    echo "📦 [1/6] Waiting for any background system locks to release..."
    while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || fuser /var/lib/dpkg/lock >/dev/null 2>&1; do
        echo "⏳ Background system update is finishing, waiting 3 seconds..."
        sleep 3
    done
    echo "📦 [1/6] Updating packages & installing Python3, Git, Nginx..."
    apt-get update -y
    apt-get install -y python3 python3-pip python3-venv git curl nginx
elif command -v dnf >/dev/null 2>&1; then
    echo "📦 [1/6] Installing Python3, Git, Nginx via DNF..."
    dnf install -y python3 python3-pip git curl nginx
elif command -v yum >/dev/null 2>&1; then
    echo "📦 [1/6] Installing Python3, Git, Nginx via YUM..."
    yum install -y python3 python3-pip git curl nginx
fi

# 2. Prepare Application Directory
echo "📂 [2/6] Setting up application workspace at $APP_DIR..."
mkdir -p "$APP_DIR"
cd "$APP_DIR"

# 3. Create Python Virtual Environment & Install Dependencies
echo "🐍 [3/6] Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Create data directory for SQLite persistent database
mkdir -p "$APP_DIR/data"
chmod -R 755 "$APP_DIR"

# 4. Create & Enable systemd 24/7 Service Daemon
echo "⚙️ [4/6] Configuring systemd background daemon ($SERVICE_NAME)..."
cat << 'EOF' > /etc/systemd/system/cmplibe-jobs.service
[Unit]
Description=cMPLiBe AIScanner Radar & Job Aggregator
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/cmplibe-job-scanner
ExecStart=/var/www/cmplibe-job-scanner/venv/bin/python -m uvicorn job_pulse.server:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cmplibe-jobs
systemctl restart cmplibe-jobs

# 5. Create 1-Click Update Script
echo "🔄 [5/6] Creating 1-Click update script (./update.sh)..."
cat << 'EOF' > "$APP_DIR/update.sh"
#!/usr/bin/env bash
set -e
echo "🚀 Updating cMPLiBe AIScanner from GitHub..."
cd /var/www/cmplibe-job-scanner
git pull origin main
source venv/bin/activate
pip install -r requirements.txt --quiet
systemctl restart cmplibe-jobs
echo "✅ cMPLiBe AIScanner reloaded successfully!"
EOF
chmod +x "$APP_DIR/update.sh"

# 6. Generate Nginx Proxy Configuration
echo "🌐 [6/6] Generating Nginx snippet for https://www.cmplibe.com/job-scanner..."
cat << 'EOF' > "$APP_DIR/nginx_job_scanner.conf"
# ==============================================================================
# Paste the following block inside your existing /etc/nginx/sites-available/cmplibe.com
# (or inside your Nginx 'server { ... }' block for www.cmplibe.com):
# ==============================================================================

location /job-scanner {
    rewrite ^/job-scanner$ /job-scanner/ permanent;
}

location /job-scanner/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /job-scanner;
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
}
EOF

echo ""
echo "=========================================================="
echo "🎉 DEPLOYMENT COMPLETE & RUNNING 24/7!"
echo "=========================================================="
echo "• Status: $(systemctl is-active cmplibe-jobs)"
echo "• Backend Port: http://127.0.0.1:8000"
echo ""
echo "To link with your main website (www.cmplibe.com):"
echo "1. Open your Nginx config: nano /etc/nginx/sites-available/default (or your domain conf)"
echo "2. Paste the block from: cat /var/www/cmplibe-job-scanner/nginx_job_scanner.conf"
echo "3. Run: nginx -t && systemctl reload nginx"
echo "4. Open: https://www.cmplibe.com/job-scanner"
echo "=========================================================="
