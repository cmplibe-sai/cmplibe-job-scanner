# 🚀 Hostinger 24/7 Permanent Deployment Guide

This guide details how to deploy **cMPLiBe AIScanner** to **Hostinger** for 100% persistent, uninterrupted 24/7 execution with **zero cold-starts and zero data wipes**.

---

## 🌟 Why Hostinger is Superior to Render Free Tier

| Feature | Render Free Tier | Hostinger VPS / Python Hosting |
| :--- | :--- | :--- |
| **Uptime** | ❌ Sleeps after 15 mins of inactivity | 🟢 **100% 24/7 Continuous Uptime** |
| **Cold Starts** | ❌ 50-second wake-up delay | 🟢 **Instant Response (0ms delay)** |
| **Storage / Database** | ❌ Ephemeral (Wipes data on restart) | 🟢 **100% Persistent NVMe SSD Storage** |
| **Background Alerts** | ❌ Pauses when container sleeps | 🟢 **24/7 Nonstop Automated Scanning** |
| **Team Members & Settings** | ❌ Erased when container sleeps | 🟢 **Permanently Saved in SQLite DB** |

---

## 🛠️ Step-by-Step Hostinger VPS Deployment

### 1. Connect to your Hostinger VPS via SSH
Open your terminal (PowerShell, Command Prompt, or PuTTY) and run:
```bash
ssh root@YOUR_HOSTINGER_SERVER_IP
```

---

### 2. Install Python 3.11 & Required Dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git nginx certbot python3-certbot-nginx
```

---

### 3. Clone Repository & Setup Virtual Environment
```bash
# Clone to /var/www/cmplibe-scanner
sudo mkdir -p /var/www
cd /var/www
git clone https://github.com/cmplibe-sai/cmplibe-job-scanner.git cmplibe-scanner
cd cmplibe-scanner

# Create and activate Python virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 4. Create Systemd Service (Ensures 24/7 Auto-Restart)
Create a background service daemon file:
```bash
sudo nano /etc/systemd/system/cmplibe-scanner.service
```

Paste the following configuration:
```ini
[Unit]
Description=cMPLiBe AIScanner 24/7 Service
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/cmplibe-scanner
Environment="PATH=/var/www/cmplibe-scanner/venv/bin"
Environment="DATA_DIR=/var/www/cmplibe-scanner/data"
Environment="SMTP_HOST=resend"
Environment="SMTP_PORT=443"
Environment="SMTP_USER=resend"
Environment="SMTP_PASSWORD=YOUR_RESEND_API_KEY"
Environment="SENDER_EMAIL=cMPLiBe AIScanner <alerts@cmplibe.com>"
Environment="RECIPIENT_EMAIL=earlitalent@cmplibe.com"
Environment="ALL_INDIA_RECIPIENT_EMAIL=earlitalent@cmplibe.com"
Environment="GOOGLE_SHEETS_SPREADSHEET_ID=1oMa1z0RilDuXmIKtgmOiY7FzudXVlI9pPKzwwMrU_4g"
ExecStart=/var/www/cmplibe-scanner/venv/bin/uvicorn job_pulse.server:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cmplibe-scanner
sudo systemctl start cmplibe-scanner
sudo systemctl status cmplibe-scanner
```

---

### 5. Configure Nginx Reverse Proxy with SSL
Create the Nginx configuration file for your custom domain `jobs.cmplibe.com`:
```bash
sudo nano /etc/nginx/sites-available/jobs.cmplibe.com
```

Paste the following Nginx block:
```nginx
server {
    listen 80;
    server_name jobs.cmplibe.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and obtain a free SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/jobs.cmplibe.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Issue Free SSL Certificate
sudo certbot --nginx -d jobs.cmplibe.com
```

---

### 6. Update DNS A-Record in Hostinger
1. Log into your **Hostinger hPanel** > **Domains** > **`cmplibe.com`** > **DNS / Nameservers**.
2. Find or add the **A Record**:
   * **Type**: `A`
   * **Name**: `jobs`
   * **Points to**: `YOUR_HOSTINGER_VPS_IP`
   * **TTL**: `3600`
3. Click **Save**.

---

### 🎉 Result
Your scanner will now be live on **`https://jobs.cmplibe.com/`**, running **24/7/365 permanently without sleeping, without cold starts, and without data loss!**
