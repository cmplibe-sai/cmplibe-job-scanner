import os
from pathlib import Path
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request, Response, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from job_pulse.models import SearchQuery, CompanyTarget, RadarAlertLog, DiscoveryAlertLog, EmailConfig, GoogleSheetsConfig
from job_pulse.orchestrator import ScraperOrchestrator
from job_pulse.storage.db import JobDatabase
from job_pulse.pipeline.exporter import JobExporter
from job_pulse.pipeline.sheets_sync import GoogleSheetsManager
from job_pulse.scrapers.career_pages import CareerPageScraper
from job_pulse.radar.scanner import CompanyRadarScanner
from job_pulse.radar.discovery_scanner import AllIndiaDiscoveryScanner
from job_pulse.radar.notifier import RadarEmailNotifier
from job_pulse.radar.scheduler import get_radar_scheduler
from job_pulse.security import create_session, validate_session, revoke_session
from job_pulse.config import DATA_DIR

root_path = os.getenv("ROOT_PATH", "").rstrip("/")
app = FastAPI(
    title="cMPLiBe's AIScanner API",
    description="Multi-Portal Job, Company Radar & Recruiter Post Aggregator • Heartland • Growth-Mindset • Opportunities",
    root_path=root_path,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = JobDatabase()
orchestrator = ScraperOrchestrator(db=db)
radar_scanner = CompanyRadarScanner(db=db)
discovery_scanner = AllIndiaDiscoveryScanner(db=db, orchestrator=orchestrator)

# Auto-start Dual Radar background scheduler
@app.on_event("startup")
def startup_event():
    scheduler = get_radar_scheduler(db)
    scheduler.start()


# Active background scraping tasks state
scraping_state = {
    "is_running": False,
    "current_query": None,
    "last_result": None,
    "progress": {},
}


# =================================================================
# Security & Authentication Models & Dependencies
# =================================================================

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: Optional[str] = "member"


class AdminResetPasswordRequest(BaseModel):
    new_password: str


def get_current_user(request: Request) -> str:
    """Extract and validate session cookie or Authorization Bearer header."""
    token = request.cookies.get("jobpulse_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    user = validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required. Please log in.")
    return user


def require_admin(request: Request, user: str = Depends(get_current_user)) -> str:
    """Require user to possess the 'admin' role."""
    role = db.get_user_role(user)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required to perform this action.")
    return user


@app.post("/api/auth/login")
def login(req: LoginRequest, response: Response):
    """Authenticate team member and establish session cookie."""
    user_info = db.verify_user_credentials(req.username, req.password)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid username or password, or account is disabled.")

    username = user_info["username"]
    role = user_info.get("role", "member")
    token = create_session(username)
    db.update_user_last_login(username)

    response.set_cookie(
        key="jobpulse_session",
        value=token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return {
        "success": True,
        "user": username,
        "role": role,
        "token": token,
        "message": "Login successful",
    }


@app.get("/api/auth/me")
def get_auth_status(request: Request):
    """Check current authentication status and user role for the dashboard UI."""
    token = request.cookies.get("jobpulse_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    username = validate_session(token)
    if not username:
        return {"authenticated": False, "user": None, "role": None}

    role = db.get_user_role(username) or "member"
    return {"authenticated": True, "user": username, "role": role}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    """Terminate active user session and delete cookie."""
    token = request.cookies.get("jobpulse_session")
    if token:
        revoke_session(token)
    response.delete_cookie("jobpulse_session")
    return {"success": True, "message": "Logged out successfully."}


@app.post("/api/auth/change-password")
def change_password(req: ChangePasswordRequest, user: str = Depends(get_current_user)):
    """Change current authenticated user's own password."""
    success, msg = db.change_user_password(user, req.old_password, req.new_password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


# =================================================================
# Admin User Management Endpoints
# =================================================================

@app.get("/api/auth/users")
def list_team_users(admin: str = Depends(require_admin)):
    """List all registered team accounts (Admin only)."""
    users = db.get_users_list()
    return {"users": users, "count": len(users)}


@app.post("/api/auth/users")
def create_team_user(req: CreateUserRequest, admin: str = Depends(require_admin)):
    """Create a new team account with specified role (Admin only)."""
    success, msg = db.add_user(req.username, req.password, req.role or "member")
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/auth/users/{target_username}/reset-password")
def admin_reset_password(target_username: str, req: AdminResetPasswordRequest, admin: str = Depends(require_admin)):
    """Reset password for a specified team member (Admin only)."""
    success, msg = db.admin_reset_user_password(target_username, req.new_password)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/auth/users/{target_username}/toggle-status")
def toggle_user_status(target_username: str, admin: str = Depends(require_admin)):
    """Activate or deactivate a team user account (Admin only)."""
    success, msg = db.admin_toggle_user_status(target_username, admin)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.delete("/api/auth/users/{target_username}")
def delete_team_user(target_username: str, admin: str = Depends(require_admin)):
    """Delete a team member account (Admin only)."""
    success, msg = db.admin_delete_user(target_username, admin)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


class DirectCareerRequest(BaseModel):
    url: str
    filter: Optional[str] = ""
    company: Optional[str] = ""


class UpdateStatusRequest(BaseModel):
    status: str


class AddTargetRequest(BaseModel):
    company_name: str
    career_url: Optional[str] = ""
    keywords: Optional[str] = ""
    channels: Optional[List[str]] = None


class TestSmtpConnectionRequest(BaseModel):
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None


class TestEmailRequest(BaseModel):
    recipient_email: str
    alert_type: Optional[str] = "target"  # 'target' or 'all_india'
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    sender_email: Optional[str] = None


class DiscoveryScanRequest(BaseModel):
    keywords: Optional[str] = None
    location: Optional[str] = "India"
    role_type: Optional[str] = "all"
    experience_level: Optional[str] = None
    send_email: bool = True
    sync_sheets: bool = True


class SheetsTestRequest(BaseModel):
    credentials_json: Optional[str] = None
    spreadsheet_id_or_url: Optional[str] = None


class SheetsSyncRequest(BaseModel):
    sync_all: bool = True
    sheet_name: Optional[str] = None
    limit: int = 1000



@app.get("/api/stats")
def get_stats(user: str = Depends(get_current_user)):
    """Get aggregated metrics."""
    return db.get_stats()


@app.get("/api/jobs")
def get_jobs(
    q: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    portal: Optional[str] = None,
    work_mode: Optional[str] = None,
    role_type: Optional[str] = None,
    experience_level: Optional[str] = None,
    internship: Optional[bool] = None,
    status: Optional[str] = None,
    favorite_only: bool = False,
    limit: int = 200,
    offset: int = 0,
    user: str = Depends(get_current_user),
):
    """Retrieve jobs with faceted filtering."""
    jobs = db.get_jobs(
        keywords=q,
        location=location,
        company=company,
        portal=portal,
        work_mode=work_mode,
        role_type=role_type,
        experience_level=experience_level,
        is_internship=internship,
        status=status,
        favorite_only=favorite_only,
        limit=limit,
        offset=offset,
    )
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/api/posts")
def get_posts(
    q: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    role_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: str = Depends(get_current_user),
):
    """Retrieve LinkedIn Recruiter/HR hiring posts."""
    posts = db.get_hiring_posts(
        keywords=q,
        location=location,
        company=company,
        role_type=role_type,
        limit=limit,
        offset=offset,
    )
    return {"posts": posts, "count": len(posts)}


def _execute_scrape(query: SearchQuery):
    global scraping_state
    scraping_state["is_running"] = True
    scraping_state["current_query"] = query.model_dump()
    scraping_state["progress"] = {p: {"status": "scraping..."} for p in query.portals}

    def on_progress(portal: str, res):
        scraping_state["progress"][portal] = {
            "status": "complete" if res.success else "failed",
            "count": res.total_found,
            "error": res.error_message,
        }

    try:
        res = orchestrator.run(query, progress_callback=on_progress)
        scraping_state["last_result"] = {
            "total_scraped": res["total_scraped"],
            "unique_jobs": res["unique_jobs"],
            "new_stored": res["new_stored"],
            "total_hiring_posts": res.get("total_hiring_posts", 0),
            "execution_time_seconds": res["execution_time_seconds"],
        }

        # Auto-sync to Google Sheets if enabled
        sheets_config = db.get_sheets_config()
        if sheets_config.get("is_enabled") and sheets_config.get("auto_sync_on_scrape") and sheets_config.get("spreadsheet_id_or_url"):
            try:
                ok_j, cnt_j, _ = GoogleSheetsManager.sync_jobs(
                    jobs=res.get("jobs", []),
                    config=sheets_config,
                    sheet_name=sheets_config.get("sheet_name_all_india", "All-India Jobs"),
                )
                ok_p, cnt_p, _ = GoogleSheetsManager.sync_hiring_posts(
                    posts=res.get("hiring_posts", []),
                    config=sheets_config,
                    sheet_name=sheets_config.get("sheet_name_hiring_posts", "Recruiter Posts"),
                )
                if (cnt_j + cnt_p) > 0:
                    db.update_sheets_sync_stats(cnt_j + cnt_p)
            except Exception as e:
                print(f"[GoogleSheets Auto-Sync Warning]: {e}")

    finally:
        scraping_state["is_running"] = False


@app.post("/api/scrape")
def trigger_scrape(query: SearchQuery, background_tasks: BackgroundTasks, user: str = Depends(get_current_user)):
    """Trigger parallel scraping across portals & recruiter posts."""
    if scraping_state["is_running"]:
        return JSONResponse(
            status_code=409,
            content={"message": "A scraping task is already running in the background."},
        )

    background_tasks.add_task(_execute_scrape, query)
    return {"message": "Scraping task initiated.", "query": query.model_dump()}


@app.get("/api/scrape/status")
def get_scrape_status(user: str = Depends(get_current_user)):
    """Poll scraping task status and live progress."""
    return scraping_state


@app.post("/api/scrape/career")
def scrape_career_url(req: DirectCareerRequest, user: str = Depends(get_current_user)):
    """Directly scrape a company career page or ATS link."""
    scraper = CareerPageScraper()
    jobs = scraper.scrape_url(req.url, keyword_filter=req.filter or "", company_override=req.company or "")
    saved_count = db.save_jobs_batch(jobs)
    return {
        "url": req.url,
        "found": len(jobs),
        "new_saved": saved_count,
        "jobs": [j.model_dump() for j in jobs],
    }


@app.post("/api/jobs/{job_id}/favorite")
def toggle_favorite(job_id: str, user: str = Depends(get_current_user)):
    success = db.toggle_favorite(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}


@app.post("/api/jobs/{job_id}/status")
def update_job_status(job_id: str, req: UpdateStatusRequest, user: str = Depends(get_current_user)):
    success = db.update_job_status(job_id, req.status)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, user: str = Depends(get_current_user)):
    success = db.delete_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True}


@app.get("/api/export")
def export_jobs(
    format: str = Query("csv", pattern="^(csv|json|md)$"),
    q: Optional[str] = None,
    location: Optional[str] = None,
    company: Optional[str] = None,
    portal: Optional[str] = None,
    work_mode: Optional[str] = None,
    role_type: Optional[str] = None,
    experience_level: Optional[str] = None,
    internship: Optional[bool] = None,
    status: Optional[str] = None,
    favorite_only: bool = False,
    user: str = Depends(get_current_user),
):
    """Export filtered jobs to CSV, JSON or Markdown."""
    jobs = db.get_jobs(
        keywords=q,
        location=location,
        company=company,
        portal=portal,
        work_mode=work_mode,
        role_type=role_type,
        experience_level=experience_level,
        is_internship=internship,
        status=status,
        favorite_only=favorite_only,
        limit=10000,
    )
    if format == "csv":
        file_path = DATA_DIR / "jobs_export.csv"
        JobExporter.to_csv(jobs, file_path)
        return FileResponse(path=file_path, filename="jobs_export.csv", media_type="text/csv")
    elif format == "json":
        file_path = DATA_DIR / "jobs_export.json"
        JobExporter.to_json(jobs, file_path)
        return FileResponse(path=file_path, filename="jobs_export.json", media_type="application/json")
    else:
        file_path = DATA_DIR / "jobs_export.md"
        JobExporter.to_markdown(jobs, file_path)
        return FileResponse(path=file_path, filename="jobs_export.md", media_type="text/markdown")


# ==========================================
# Company Radar & Automated Email Alert Endpoints
# ==========================================

@app.get("/api/radar/targets")
def list_radar_targets(user: str = Depends(get_current_user)):
    """List all watched target companies with scan status."""
    targets = db.get_company_targets()
    return {"targets": targets, "count": len(targets)}


@app.post("/api/radar/targets")
def add_radar_target(req: AddTargetRequest, user: str = Depends(get_current_user)):
    """Add a new company to the Radar watchlist."""
    channels = req.channels or ["ats", "linkedin", "internshala", "unstop", "shine", "social_posts"]
    target = CompanyTarget(
        company_name=req.company_name.strip(),
        career_url=req.career_url.strip() if req.career_url else "",
        keywords=req.keywords.strip() if req.keywords else "",
        channels=channels,
    )
    is_new = db.save_company_target(target)
    return {"success": True, "target": target.model_dump(), "is_new": is_new}


@app.post("/api/radar/targets/{target_id}/toggle")
def toggle_radar_target(target_id: str, user: str = Depends(get_current_user)):
    """Toggle monitoring on/off for a watched company."""
    success = db.toggle_company_target(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="Target company not found")
    return {"success": True}


@app.delete("/api/radar/targets/{target_id}")
def delete_radar_target(target_id: str, user: str = Depends(get_current_user)):
    """Delete a company from the Radar watchlist."""
    success = db.delete_company_target(target_id)
    if not success:
        raise HTTPException(status_code=404, detail="Target company not found")
    return {"success": True}


@app.get("/api/radar/settings")
def get_radar_settings(user: str = Depends(get_current_user)):
    """Fetch current email notification and Radar settings."""
    return db.get_email_config()


@app.post("/api/radar/settings")
def save_radar_settings(config: EmailConfig, user: str = Depends(get_current_user)):
    """Save SMTP email and Radar background interval settings without losing existing passwords."""
    curr = db.get_email_config()
    cfg_dict = config.model_dump()
    # Preserve existing password if user left password field blank when saving recipients
    if not cfg_dict.get("smtp_password") and curr.get("smtp_password"):
        cfg_dict["smtp_password"] = curr["smtp_password"]
    db.save_email_config(cfg_dict)
    return {"success": True, "settings": db.get_email_config()}


@app.post("/api/radar/test-connection")
def test_smtp_connection(req: TestSmtpConnectionRequest, user: str = Depends(get_current_user)):
    """Test SMTP mail server connection and authentication without sending an email."""
    curr = db.get_email_config()
    smtp_dict = {
        "smtp_host": (req.smtp_host or "").strip() or curr.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": req.smtp_port or curr.get("smtp_port", 465),
        "smtp_user": (req.smtp_user or "").strip() or curr.get("smtp_user", ""),
        "smtp_password": (req.smtp_password or "").strip() or curr.get("smtp_password", ""),
    }
    success, msg, recommended_port = RadarEmailNotifier.test_smtp_connection(smtp_dict)
    if not success:
        return JSONResponse(status_code=400, content={"success": False, "message": msg, "recommended_port": recommended_port})
    return {"success": True, "message": msg, "recommended_port": recommended_port}


@app.post("/api/radar/test-email")
def test_radar_email(req: TestEmailRequest, user: str = Depends(get_current_user)):
    """Test SMTP email delivery with current or provided credentials."""
    curr = db.get_email_config()
    smtp_dict = {
        "smtp_host": (req.smtp_host or "").strip() or curr.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": req.smtp_port or curr.get("smtp_port", 465),
        "smtp_user": (req.smtp_user or "").strip() or curr.get("smtp_user", ""),
        "smtp_password": (req.smtp_password or "").strip() or curr.get("smtp_password", ""),
        "sender_email": (req.sender_email or "").strip() or curr.get("sender_email", ""),
    }
    success, msg = RadarEmailNotifier.send_test_email(smtp_dict, req.recipient_email)
    if not success:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return {"success": True, "message": msg}


@app.post("/api/radar/scan")
def trigger_radar_scan(background_tasks: BackgroundTasks, target_id: Optional[str] = None, user: str = Depends(get_current_user)):
    """Trigger an immediate radar scan across watchlist companies."""
    def _run_scan():
        if target_id:
            t_data = db.get_company_target(target_id)
            if t_data:
                target_obj = CompanyTarget(**t_data)
                radar_scanner.scan_target(target_obj, send_email=True)
        else:
            radar_scanner.scan_all_targets(send_email=True)

    background_tasks.add_task(_run_scan)
    return {"message": "Target Company Radar scan initiated in background."}


@app.get("/api/radar/logs")
def get_radar_logs(limit: int = 50, user: str = Depends(get_current_user)):
    """Retrieve history of emailed Target Company Radar opportunity alerts."""
    logs = db.get_radar_alert_logs(limit=limit)
    return {"logs": logs, "count": len(logs)}


# ==========================================
# All-India Multi-Portal Opportunity Radar Endpoints
# ==========================================

@app.post("/api/radar/discovery/scan")
def trigger_discovery_scan(req: DiscoveryScanRequest, background_tasks: BackgroundTasks, user: str = Depends(get_current_user)):
    """Trigger an immediate broad All-India multi-portal discovery scan."""
    def _run_discovery():
        discovery_scanner.scan_all_india(
            keywords=req.keywords,
            location=req.location or "India",
            role_type=req.role_type or "all",
            experience_level=req.experience_level,
            send_email=req.send_email,
            sync_sheets=req.sync_sheets,
        )

    background_tasks.add_task(_run_discovery)
    return {"message": "All-India Opportunity Radar scan initiated in background."}


@app.get("/api/radar/discovery/logs")
def get_discovery_logs(limit: int = 50, user: str = Depends(get_current_user)):
    """Retrieve history of emailed All-India Opportunity alerts."""
    logs = db.get_discovery_alert_logs(limit=limit)
    return {"logs": logs, "count": len(logs)}


# ==========================================
# Google Sheets Live Sync Endpoints
# ==========================================

@app.get("/api/sheets/settings")
def get_sheets_settings(user: str = Depends(get_current_user)):
    """Fetch current Google Sheets live sync settings and statistics."""
    return db.get_sheets_config()


@app.post("/api/sheets/settings")
def save_sheets_settings(config: GoogleSheetsConfig, user: str = Depends(get_current_user)):
    """Save Google Sheets synchronization configuration."""
    curr = db.get_sheets_config()
    cfg_dict = config.model_dump()
    # Preserve existing credentials JSON if left empty
    if not cfg_dict.get("credentials_json") and curr.get("credentials_json"):
        cfg_dict["credentials_json"] = curr["credentials_json"]
    if not cfg_dict.get("spreadsheet_id_or_url") and curr.get("spreadsheet_id_or_url"):
        cfg_dict["spreadsheet_id_or_url"] = curr["spreadsheet_id_or_url"]
    db.save_sheets_config(cfg_dict)
    return {"success": True, "settings": db.get_sheets_config()}


@app.post("/api/sheets/test")
def test_sheets_connection(req: SheetsTestRequest, user: str = Depends(get_current_user)):
    """Test Google Sheets authentication and spreadsheet permissions."""
    curr = db.get_sheets_config()
    test_dict = {
        "credentials_json": (req.credentials_json or "").strip() or curr.get("credentials_json", ""),
        "spreadsheet_id_or_url": (req.spreadsheet_id_or_url or "").strip() or curr.get("spreadsheet_id_or_url", ""),
    }
    success, msg = GoogleSheetsManager.test_connection(test_dict)
    if not success:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return {"success": True, "message": msg}


@app.post("/api/sheets/sync")
def sync_to_google_sheets(req: SheetsSyncRequest, background_tasks: BackgroundTasks, user: str = Depends(get_current_user)):
    """Trigger a synchronization of database jobs and hiring posts to Google Sheets."""
    sheets_config = db.get_sheets_config()
    if not sheets_config.get("is_enabled"):
        return JSONResponse(status_code=400, content={"success": False, "message": "Google Sheets live sync is currently disabled in settings."})

    def _execute_sync():
        jobs = db.get_jobs(limit=req.limit)
        posts = db.get_hiring_posts(limit=req.limit)

        ok_j, cnt_j, msg_j = GoogleSheetsManager.sync_jobs(
            jobs=jobs,
            config=sheets_config,
            sheet_name=req.sheet_name or sheets_config.get("sheet_name_all_india", "All-India Jobs"),
        )
        ok_p, cnt_p, msg_p = GoogleSheetsManager.sync_hiring_posts(
            posts=posts,
            config=sheets_config,
            sheet_name=sheets_config.get("sheet_name_hiring_posts", "Recruiter Posts"),
        )
        total_synced = cnt_j + cnt_p
        if total_synced > 0:
            db.update_sheets_sync_stats(total_synced)

    background_tasks.add_task(_execute_sync)
    return {"message": "Google Sheets synchronization initiated in background."}


@app.post("/api/sheets/clean")
def clean_google_sheets(background_tasks: BackgroundTasks, user: str = Depends(get_current_user)):
    """Scan and purge non-job navigation links from connected Google Sheet worksheets."""
    sheets_config = db.get_sheets_config()
    if not sheets_config.get("spreadsheet_id_or_url"):
        return JSONResponse(status_code=400, content={"success": False, "message": "Google Spreadsheet ID/URL is not configured."})

    success, purged_count, msg = GoogleSheetsManager.clean_worksheet_junk_rows(sheets_config)
    if not success:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return {"success": True, "purged_count": purged_count, "message": msg}


# Mount static assets for the Dashboard UI
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


