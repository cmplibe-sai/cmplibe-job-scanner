# 🚀 Hostinger 24/7 Permanent Deployment Guide
### Target Live URL: `https://www.cmplibe.com/job-scanner`

This guide explains how to deploy **cMPLiBe AIScanner** directly onto your **Hostinger VPS / Server** so it runs at `https://www.cmplibe.com/job-scanner` alongside your existing `www.cmplibe.com` website without modifying or touching your other website files.

---

## 🌟 Key Architecture & Benefits
* **Preserves Main Website**: Your main website at `www.cmplibe.com` remains 100% untouched. No new visible navigation tabs are added.
* **Direct Subpath Access**: Navigating to `https://www.cmplibe.com/job-scanner` immediately opens the secure Job Scanner portal.
* **100% 24/7 Persistent Storage**: All watched target companies, team member accounts, Google Sheets live syncs, and Resend email alerts run 24/7 in the background without sleeping or data resets.

---

## 🛠️ 1-Click Automated Setup (Fastest & Easiest)

### Step 1: Open Terminal on Hostinger
1. Log into your **Hostinger hPanel**.
2. Go to **VPS** > Click **Browser Terminal** (or connect via SSH: `ssh root@YOUR_HOSTINGER_IP`).

### Step 2: Clone and Run `deploy.sh`
Paste the following 4 lines into your Hostinger terminal:

```bash
# 1. Clone repository from GitHub
git clone https://github.com/cmplibe-sai/cmplibe-job-scanner.git /var/www/cmplibe-job-scanner
cd /var/www/cmplibe-job-scanner

# 2. Make deployment script executable and run it
chmod +x deploy.sh update.sh
./deploy.sh
```

The script will automatically:
1. Install Python 3, Git, and Nginx.
2. Build the Python virtual environment and install all packages.
3. Create the 24/7 background system service (`cmplibe-jobs.service`) and start it.

---

### Step 3: Link `www.cmplibe.com` to `/job-scanner` in Nginx

1. Open your existing Nginx website configuration on Hostinger:
   ```bash
   sudo nano /etc/nginx/sites-available/default
   # (Or /etc/nginx/sites-available/cmplibe.com depending on your Nginx setup)
   ```

2. Inside your `server { ... }` block for `www.cmplibe.com`, paste this block:

   ```nginx
   # Route /job-scanner to cMPLiBe AIScanner
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
   ```

3. Test and reload Nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

---

## 🔄 How Future Updates Work (1-Click)

Whenever new code is pushed to GitHub, update your live server in 3 seconds by running:

```bash
cd /var/www/cmplibe-job-scanner
./update.sh
```

---

## 📋 Useful Server Commands

| Action | Command |
| :--- | :--- |
| **Check Scanner Status** | `systemctl status cmplibe-jobs` |
| **View Live Logs** | `journalctl -u cmplibe-jobs -f` |
| **Restart Scanner** | `systemctl restart cmplibe-jobs` |
| **Stop Scanner** | `systemctl stop cmplibe-jobs` |
