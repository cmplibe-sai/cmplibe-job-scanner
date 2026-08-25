# 🚀 24/7 Cloud Deployment & Team Security Guide

This guide explains how to deploy **cMPLiBe's AIScanner** to a cloud server so that it continues scanning portals, sending dual email alerts, and synchronizing with Google Sheets **24/7 non-stop, even when your laptop or computer is turned off**.

---

## 🔐 1. Team Authentication & Security Layer

When the system is deployed live on the web, anyone visiting the URL is blocked by a **Security Login Gate**:

- **Default Username**: `admin`
- **Default Password**: `cmplibe@2026`
- **Session Security**: Authenticated sessions receive a cryptographic `HttpOnly` cookie valid for 7 days.
- **Changing Your Password**:
  1. Open the Web Dashboard and log in.
  2. Navigate to the **Email & System Settings ⚙️** tab.
  3. Under the **Team Password & Security Credentials** section, enter your current password and set a new password.
  4. Alternatively, you can set the `ADMIN_PASSWORD` environment variable on your cloud host.

---

## ☁️ 2. Cloud Deployment Options

### Option A: Render.com (Recommended — Fast & Low Maintenance)

Render provides automatic deployments from GitHub with SSL certificates and persistent storage.

1. Push your repository to **GitHub** (Private or Public).
2. Sign up at [Render.com](https://render.com).
3. Click **New +** > **Web Service** > Connect your GitHub repository.
4. Configure the service:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn job_pulse.server:app --host 0.0.0.0 --port $PORT`
   - **Plan**: Starter or Free
5. **Add Persistent Disk** (to preserve SQLite database across restarts):
   - In your Render service settings, go to **Disks** > **Add Disk**.
   - **Mount Path**: `/app/data`
   - **Size**: `1 GB` (or more).
6. **Environment Variables**:
   - `DATA_DIR`: `/app/data`
   - `ADMIN_PASSWORD`: `YourSecurePassword2026`
7. Click **Create Web Service**. Your live URL (e.g. `https://cmplibe-aiscanner.onrender.com`) is now active 24/7!

---

### Option B: Railway.app (1-Click Deployment)

1. Sign up at [Railway.app](https://railway.app).
2. Click **New Project** > **Deploy from GitHub repo**.
3. Railway automatically detects the `Procfile` and `requirements.txt`.
4. Add a **Volume**:
   - Go to **Settings** > **Volumes** > **Add Volume**.
   - Mount path: `/app/data`.
5. Under **Variables**, add:
   - `DATA_DIR`: `/app/data`
   - `ADMIN_PASSWORD`: `YourSecurePassword2026`
6. Click **Generate Domain** to get your public HTTPS URL.

---

### Option C: Any Linux Cloud VPS (AWS EC2, DigitalOcean, Google Cloud, Linode)

If you have an Ubuntu/Debian virtual private server (e.g., a $4-6/month DigitalOcean Droplet or AWS t3.micro EC2 instance):

#### Method 1: Using Docker Compose (Fastest & Simplest)

1. SSH into your VPS:
   ```bash
   ssh root@your-server-ip
   ```
2. Clone your project repository:
   ```bash
   git clone <your-repo-url> /opt/aiscanner
   cd /opt/aiscanner
   ```
3. Start the container in background daemon mode:
   ```bash
   docker compose up -d --build
   ```
4. The system is now live at `http://your-server-ip:8000` and will automatically restart if the server reboots (`restart: unless-stopped`).

#### Method 2: Running as a Linux `systemd` Service

1. On your VPS, install Python 3.11:
   ```bash
   sudo apt update && sudo apt install -y python3-pip python3-venv git
   ```
2. Create virtual environment and install requirements:
   ```bash
   cd /opt/aiscanner
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Create a systemd service file:
   ```bash
   sudo nano /etc/systemd/system/aiscanner.service
   ```

---

## 🌐 3. Hosting on Subpath: `https://cmplibe.com/sourcing-opportunities`

If you want the application to be accessible directly under your company domain at **`https://cmplibe.com/sourcing-opportunities`**:

### Step 1: Set `ROOT_PATH` Environment Variable
Configure `ROOT_PATH` so FastAPI knows it is being served behind a reverse proxy subpath:
```bash
export ROOT_PATH=/sourcing-opportunities
```
Or in your `.env` or systemd service / docker-compose environment:
```yaml
environment:
  - ROOT_PATH=/sourcing-opportunities
  - ADMIN_PASSWORD=cmplibe@2026
```

### Step 2: Nginx Reverse Proxy Configuration
Add the following `location` block into the `server` block of your `cmplibe.com` Nginx configuration file (usually `/etc/nginx/sites-available/cmplibe.com`):

```nginx
# ================================================================
# cMPLiBe Sourcing Opportunities & AIScanner Reverse Proxy
# ================================================================
location /sourcing-opportunities/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_http_version 1.1;
    
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /sourcing-opportunities;
    
    # Timeout configurations for deep scans
    proxy_read_timeout 300s;
    proxy_connect_timeout 75s;
}

# Redirect trailing slash if someone visits /sourcing-opportunities
location = /sourcing-opportunities {
    return 301 /sourcing-opportunities/;
}
```

Reload Nginx:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 👥 4. Multi-User Team & Admin Access Control

1. **Master Admin**:
   - Initial credentials: `admin` / `cmplibe@2026`
   - Master Admin cannot be deleted or disabled.
2. **Adding Team Members**:
   - Go to **Settings ⚙️** > **Team User Accounts & Access Management**.
   - Enter a **Username** (e.g. `rahul_recruiter`), **Initial Password**, and select role (`Member` or `Admin`).
   - Click **Create User Account**.
3. **User Roles**:
   - **Admin**: Has complete control over all scanners, settings, email digests, Google Sheet sync, and can add users, reset user passwords, disable, or delete team accounts.
   - **Member**: Can use the multi-portal search, run company radar scans, filter jobs, toggle favorites, and update their own password, but cannot modify team users.
4. **Password Self-Service**:
   - Any logged-in team member can change their own password at any time under **Settings ⚙️** > **My Account Password**.

---

## 📊 5. Google Sheets & Dual Email Alerts (Always Active in Cloud)

When deployed to your cloud server:
- **Target Company Radar**: Runs automatically on its configured schedule (e.g. every 60 mins) and syncs new postings into the *Target Company Radar* tab of your Google Sheet and sends email alerts.
- **All-India Discovery Radar**: Runs automatically on its configured schedule (e.g. every 120 mins) and syncs across India into the *All-India Jobs* tab and sends All-India email alerts.
- **IST Timezone**: All Google Sheet timestamps and UI logs display in standard **Indian Standard Time (IST, UTC+05:30)**:
  - **Google Sheets**: Column M formats timestamps as `YYYY-MM-DD HH:MM:SS IST`.
  - **Email Alerts**: Email headers & footers display timestamps as `DD Mon YYYY, HH:MM AM/PM IST`.
  - **Dashboard UI**: Displays Last Synced and Dispatched Logs in clean Indian time (`25 Aug 2026, 11:30 AM IST`).
