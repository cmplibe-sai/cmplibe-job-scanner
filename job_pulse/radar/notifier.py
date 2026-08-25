import smtplib
import ssl
import logging
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

logger = logging.getLogger("job_pulse.radar.notifier")


class IPv4SMTP_SSL(smtplib.SMTP_SSL):
    """Custom SMTP_SSL client forcing IPv4 address resolution to prevent [Errno 101] Network is unreachable on cloud hosts without IPv6 gateways."""
    def __init__(self, host="", port=0, **kwargs):
        self._target_hostname = host
        super().__init__(**kwargs)

    def _get_socket(self, host, port, timeout):
        import socket
        target = self._target_hostname or host
        addr_info = socket.getaddrinfo(target, port, socket.AF_INET, socket.SOCK_STREAM)
        ip = addr_info[0][4][0]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        timeout_val = timeout if isinstance(timeout, (int, float)) else 15.0
        s.settimeout(timeout_val)
        s.connect((ip, port))
        return self.context.wrap_socket(s, server_hostname=target)


class IPv4SMTP(smtplib.SMTP):
    """Custom SMTP client forcing IPv4 address resolution to prevent [Errno 101] Network is unreachable on cloud hosts."""
    def __init__(self, host="", port=0, **kwargs):
        self._target_hostname = host
        super().__init__(**kwargs)

    def _get_socket(self, host, port, timeout):
        import socket
        target = self._target_hostname or host
        addr_info = socket.getaddrinfo(target, port, socket.AF_INET, socket.SOCK_STREAM)
        ip = addr_info[0][4][0]
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        timeout_val = timeout if isinstance(timeout, (int, float)) else 15.0
        s.settimeout(timeout_val)
        s.connect((ip, port))
        return s


class RadarEmailNotifier:
    """Handles HTML email generation and SMTP delivery for cMPLiBe's AIScanner Company Radar."""

    @classmethod
    def _create_smtp_connection(cls, config: Dict[str, Any]) -> smtplib.SMTP:
        """Create and authenticate an SMTP connection supporting standard TLS (587) or SSL (465) with IPv4 resolution and SNI validation."""
        host = config.get("smtp_host", "smtp.gmail.com").strip()
        port = int(config.get("smtp_port", 465))
        user = config.get("smtp_user", "").strip()
        password = config.get("smtp_password", "").strip()

        context = ssl.create_default_context()

        def _connect_to(target_port: int) -> smtplib.SMTP:
            if target_port == 465:
                srv = IPv4SMTP_SSL(host=host, context=context, timeout=15)
                srv.connect(host, target_port)
                srv.ehlo()
            else:
                srv = IPv4SMTP(host=host, timeout=15)
                srv.connect(host, target_port)
                srv.ehlo()
                srv._host = host
                srv.starttls(context=context)
                srv.ehlo()

            if user and password:
                srv.login(user, password)
            return srv

        # Try requested port first
        try:
            return _connect_to(port)
        except Exception as primary_err:
            # If primary port timed out or was blocked by firewall, automatically attempt alternate port
            alt_port = 465 if port != 465 else 587
            logger.warning(f"SMTP connection to {host}:{port} failed ({primary_err}). Trying fallback port {alt_port}...")
            try:
                srv = _connect_to(alt_port)
                logger.info(f"Successfully established fallback SMTP connection on {host}:{alt_port}")
                return srv
            except Exception as alt_err:
                logger.error(f"Both primary ({port}) and fallback ({alt_port}) SMTP ports failed for {host}. Primary: {primary_err}; Fallback: {alt_err}")
                raise primary_err

    @classmethod
    def test_smtp_connection(cls, config: Dict[str, Any]) -> Tuple[bool, str, int]:
        """Test SMTP server connectivity and authentication without dispatching an email."""
        host = config.get("smtp_host", "smtp.gmail.com").strip()
        port = int(config.get("smtp_port", 465))
        user = config.get("smtp_user", "").strip()
        password = config.get("smtp_password", "").strip()

        if not host:
            return False, "SMTP server host is required.", port
        if not user or not password:
            return False, "SMTP username and password / app password are required.", port

        try:
            server = cls._create_smtp_connection(config)
            actual_port = getattr(server, "port", port)
            try:
                server.quit()
            except Exception:
                pass
            return True, f"Successfully connected & authenticated with {host}:{actual_port}!", actual_port
        except smtplib.SMTPAuthenticationError as e:
            return False, f"Authentication failed: Invalid login email or password ({e}). For Google Workspace / Gmail, ensure you are using a 16-character Google App Password (not your regular account password).", port
        except Exception as e:
            err_msg = str(e)
            if "timed out" in err_msg.lower() or "timeout" in err_msg.lower():
                alt_hint = "587 (TLS)" if port == 465 else "465 (SSL)"
                return False, f"Connection timed out to {host}:{port}. Cloud hosting or network firewalls may be blocking this port. Please try port {alt_hint}.", (587 if port == 465 else 465)
            return False, f"Connection test failed: {err_msg}", port

    @staticmethod
    def _format_location_and_mode(job: Dict[str, Any]) -> str:
        """Clean location and work mode string to prevent leaking enum code, raw UNKNOWN, or dictionary dumps."""
        from job_pulse.models import clean_location_string
        raw_loc = clean_location_string(job.get("location"))
        raw_mode = str(job.get("work_mode") or "").strip()

        # Clean work mode string
        clean_mode = raw_mode.replace("WorkMode.", "").replace("UNKNOWN", "").strip()
        if clean_mode.lower() in ["unknown", "not specified", "none", "null", ""]:
            clean_mode = ""

        # Clean location string
        is_loc_unspecified = not raw_loc or raw_loc.lower() in ["not specified", "unknown", "none", "null", "as announced", ""]
        
        if is_loc_unspecified:
            if clean_mode.lower() == "remote":
                return "📍 Remote (Work from Anywhere)"
            elif clean_mode.lower() in ["hybrid", "on-site", "onsite"]:
                return f"📍 As Announced • {clean_mode.title()}"
            else:
                return "📍 Location: As Announced"
        else:
            # Valid location present
            if clean_mode and clean_mode.lower() not in raw_loc.lower() and clean_mode.lower() not in ["not specified", "unknown"]:
                return f"📍 {raw_loc} • {clean_mode.title()}"
            else:
                return f"📍 {raw_loc}"

    @classmethod
    def send_test_email(cls, config: Dict[str, Any], recipient: str) -> Tuple[bool, str]:
        """Send a test email to verify SMTP configuration."""
        if not recipient:
            return False, "Recipient email address is required."

        sender = config.get("sender_email") or config.get("smtp_user") or "aiscanner@cmplibe.com"
        
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "✓ cMPLiBe's AIScanner: Email Alert System Connected Successfully"
        msg["From"] = f"cMPLiBe's AIScanner <{sender}>"
        msg["To"] = recipient

        from job_pulse.utils.time_utils import get_ist_display
        now_ist = get_ist_display()

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b1120; color: #f1f5f9; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #0284c7, #0f766e); padding: 28px 24px; }}
            .header h1 {{ margin: 0; font-size: 24px; color: #ffffff; }}
            .header p {{ margin: 6px 0 0 0; color: #bae6fd; font-size: 13px; font-weight: 500; }}
            .content {{ padding: 24px; }}
            .badge {{ display: inline-block; background: #10b981; color: #ffffff; padding: 4px 10px; border-radius: 9999px; font-weight: bold; font-size: 12px; }}
            .info-box {{ background: #0f172a; border-radius: 8px; padding: 16px; margin: 20px 0; border-left: 4px solid #0ea5e9; font-size: 14px; line-height: 1.6; }}
            .footer {{ padding: 16px 24px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #334155; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>📡 cMPLiBe's AIScanner</h1>
              <p>Heartland • Growth-Mindset • Opportunities</p>
            </div>
            <div class="content">
              <span class="badge">Connection Verified</span>
              <h2 style="color: #ffffff; margin-top: 12px;">Radar Notifications Are Active!</h2>
              <p>This test confirms that your SMTP mail settings are configured properly. You will now receive automated email alerts whenever your watched target companies publish new openings, fresher profiles, internships, or recruiter hiring requirements.</p>
              <div class="info-box">
                <strong>Configured SMTP Host:</strong> {config.get('smtp_host')}:{config.get('smtp_port')}<br>
                <strong>Sender Address:</strong> {sender}<br>
                <strong>Timestamp:</strong> {now_ist}
              </div>
            </div>
            <div class="footer">
              Sent automatically by cMPLiBe's AIScanner • Multi-Portal Intelligence Aggregator
            </div>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        try:
            with cls._create_smtp_connection(config) as server:
                server.sendmail(sender, [recipient], msg.as_string())
            return True, f"Test email successfully sent to {recipient}"
        except smtplib.SMTPAuthenticationError as e:
            return False, f"SMTP Authentication failed: Invalid username or password ({e})"
        except Exception as e:
            logger.error(f"Failed to send test email: {e}")
            return False, f"Email delivery failed: {str(e)}"

    @staticmethod
    def _is_valid_job_for_email(job: Dict[str, Any], target_company: str = "") -> bool:
        """Strictly ensures an item has a valid job title, belongs to target company, and has a direct application URL."""
        from job_pulse.models import is_valid_job_listing
        title = str(job.get("title") or "").strip()
        url = str(job.get("url") or "").strip()
        comp = str(job.get("company") or "").strip()
        return is_valid_job_listing(title=title, url=url, company=comp, target_company=target_company)

    @classmethod
    def send_radar_alert(
        cls,
        company_name: str,
        new_jobs: List[Dict[str, Any]],
        new_posts: List[Dict[str, Any]],
        recipient: str,
        config: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Format and send rich HTML notification for newly discovered target company roles & posts."""
        if not recipient:
            return False, "No recipient email provided."

        # Filter out non-job titles, invalid URLs, and mismatched companies
        valid_jobs = [j for j in new_jobs if cls._is_valid_job_for_email(j, target_company=company_name)]
        valid_posts = [p for p in new_posts if company_name.lower() in str(p.get("company", "")).lower() or company_name.lower() in str(p.get("post_text", "")).lower()]

        if not valid_jobs and not valid_posts:
            return True, "No new valid opportunities to email."

        sender = config.get("sender_email") or config.get("smtp_user") or "aiscanner@cmplibe.com"
        total_items = len(valid_jobs) + len(valid_posts)

        subject = f"🎯 Radar Alert: {total_items} New Opportunities at {company_name}"
        
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"cMPLiBe's AIScanner <{sender}>"
        msg["To"] = recipient

        # Build Job Cards HTML
        jobs_html = ""
        for job in valid_jobs:
            exp_badge = job.get("experience_text") or ("🎓 Internship / Fresher" if job.get("is_internship") else "⚡ All Experience Levels")
            loc_mode_text = cls._format_location_and_mode(job)
            portal = job.get("source_portal") or "Career Site"
            url = job.get("url") or "#"
            title = job.get("title") or "Opportunity"

            jobs_html += f"""
            <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 12px;">
              <div style="margin-bottom: 8px;">
                <h3 style="margin: 0; font-size: 16px; color: #38bdf8;">
                  <a href="{url}" style="color: #38bdf8; text-decoration: none; font-weight: 600;">{title}</a>
                </h3>
              </div>
              <div style="margin: 8px 0; font-size: 13px; line-height: 1.9;">
                <span style="display: inline-block; background: #1e293b; color: #a5b4fc; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">🌐 {portal}</span>
                <span style="display: inline-block; background: #1e293b; color: #34d399; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">💼 {exp_badge}</span>
                <span style="display: inline-block; background: #1e293b; color: #f472b6; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">{loc_mode_text}</span>
              </div>
              <div style="margin-top: 12px;">
                <a href="{url}" style="display: inline-block; background: #0284c7; color: #ffffff; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; text-decoration: none;">
                  Apply / View Opening →
                </a>
              </div>
            </div>
            """

        # Build Recruiter Posts HTML
        posts_html = ""
        for post in new_posts:
            poster = post.get("poster_name") or "HR / Recruiter"
            role = post.get("role_title") or "Hiring Opportunity"
            snippet = (post.get("post_text") or "")[:280] + ("..." if len(post.get("post_text") or "") > 280 else "")
            post_url = post.get("post_url") or "#"
            contact = post.get("contact_email") or post.get("contact_phone") or "Via LinkedIn"

            posts_html += f"""
            <div style="background: #0f172a; border: 1px solid #475569; border-radius: 8px; padding: 16px; margin-bottom: 12px; border-left: 4px solid #ec4899;">
              <div style="margin-bottom: 6px;">
                <span style="color: #ec4899; font-weight: bold; font-size: 13px;">📢 Recruiter / HR Post</span> • 
                <strong style="color: #f8fafc; font-size: 13px;">{poster}</strong>
              </div>
              <h4 style="margin: 4px 0 8px 0; font-size: 15px; color: #f1f5f9;">Role: {role}</h4>
              <p style="font-size: 13px; color: #cbd5e1; background: #1e293b; padding: 10px; border-radius: 6px; font-style: italic; margin: 8px 0;">
                "{snippet}"
              </p>
              <div style="font-size: 12px; color: #34d399; margin: 8px 0;">
                <strong>Contact / Info:</strong> {contact}
              </div>
              <div style="margin-top: 10px;">
                <a href="{post_url}" style="display: inline-block; background: #db2777; color: #ffffff; padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 600; text-decoration: none;">
                  View LinkedIn Post & Apply →
                </a>
              </div>
            </div>
            """

        from job_pulse.utils.time_utils import get_ist_display
        now_ist = get_ist_display()

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b1120; color: #f1f5f9; padding: 20px; }}
            .container {{ max-width: 640px; margin: 0 auto; background: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #0284c7, #0f766e); padding: 28px 24px; }}
            .header h1 {{ margin: 0; font-size: 22px; color: #ffffff; }}
            .header p {{ margin: 6px 0 0 0; color: #e0f2fe; font-size: 13px; }}
            .content {{ padding: 24px; }}
            .section-title {{ font-size: 16px; color: #f8fafc; font-weight: bold; margin: 20px 0 10px 0; border-bottom: 1px solid #334155; padding-bottom: 6px; }}
            .footer {{ padding: 16px 24px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #334155; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>🎯 cMPLiBe's AIScanner Target Company Radar</h1>
              <p>Fresh opportunities detected for <strong>{company_name}</strong> • Heartland • Growth-Mindset • Opportunities</p>
            </div>
            <div class="content">
              <p style="margin-top: 0; font-size: 14px; color: #cbd5e1;">
                cMPLiBe's AIScanner detected <strong>{total_items} newly posted opening(s) & requirement(s)</strong> matching your target watchlist for <strong>{company_name}</strong> across official career portals, ATS, and recruiter feeds.
              </p>

              {f'<div class="section-title">💼 Open Job Vacancies ({len(valid_jobs)})</div>' + jobs_html if valid_jobs else ''}
              {f'<div class="section-title">📢 Recruiter & Hiring Posts ({len(new_posts)})</div>' + posts_html if new_posts else ''}

            </div>
            <div class="footer">
              cMPLiBe's AIScanner Target Company Radar • Generated on {now_ist}
            </div>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        try:
            with cls._create_smtp_connection(config) as server:
                server.sendmail(sender, [recipient], msg.as_string())
            logger.info(f"Successfully emailed radar alert for '{company_name}' to {recipient}")
            return True, f"Emailed {total_items} new alert(s) for {company_name} to {recipient}"
        except Exception as e:
            logger.error(f"Failed to email radar alert for {company_name}: {e}")
            return False, str(e)

    @classmethod
    def send_all_india_alert(
        cls,
        new_jobs: List[Dict[str, Any]],
        new_posts: List[Dict[str, Any]],
        recipient: str,
        config: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Format and send rich HTML notification for broad All-India multi-portal job discoveries
        across all companies, locations, internships, and recruiter posts.
        """
        if not recipient:
            return False, "No recipient email provided for All-India alerts."

        valid_jobs = [j for j in new_jobs if cls._is_valid_job_for_email(j)]
        valid_posts = list(new_posts)

        if not valid_jobs and not valid_posts:
            return True, "No new valid opportunities to email for All-India discovery."

        sender = config.get("sender_email") or config.get("smtp_user") or "aiscanner@cmplibe.com"
        total_items = len(valid_jobs) + len(valid_posts)

        # Count metrics for digest
        tech_count = sum(1 for j in valid_jobs if str(j.get("role_type", "")).lower() in ["technical", "roletype.technical"])
        nontech_count = len(valid_jobs) - tech_count
        intern_count = sum(1 for j in valid_jobs if j.get("is_internship"))

        subject = f"🇮🇳 All-India Job Alert: {total_items} New Opportunities Discovered"

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"cMPLiBe's AIScanner (All-India Radar) <{sender}>"
        msg["To"] = recipient

        # Build Job Cards HTML
        jobs_html = ""
        for job in valid_jobs[:35]:  # Send up to top 35 in email digest with direct links
            title = job.get("title") or "Position"
            company = job.get("company") or "Company"
            portal = job.get("source_portal") or "Job Portal"
            loc_mode_text = cls._format_location_and_mode(job)
            exp_badge = job.get("experience_text") or ("🎓 Internship / Fresher" if job.get("is_internship") else "⚡ All Experience Levels")
            sal_text = job.get("salary_text")
            role_type = "💻 Technical" if str(job.get("role_type", "")).lower() in ["technical", "roletype.technical"] else "👔 Non-Technical"
            url = job.get("url") or "#"

            sal_badge = f'<span style="display: inline-block; background: #1e293b; color: #fbbf24; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">💰 {sal_text}</span>' if sal_text and sal_text != "Not Disclosed" else ''

            jobs_html += f"""
            <div style="background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px;">
              <div style="margin-bottom: 6px;">
                <h3 style="margin: 0; font-size: 15px; color: #38bdf8;">
                  <a href="{url}" style="color: #38bdf8; text-decoration: none; font-weight: 600;">{title}</a>
                </h3>
              </div>
              <div style="font-size: 13px; color: #f8fafc; font-weight: 600; margin-bottom: 6px;">
                🏢 {company}
              </div>
              <div style="margin: 8px 0; font-size: 12px; line-height: 1.9;">
                <span style="display: inline-block; background: #1e293b; color: #38bdf8; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">🌐 {portal}</span>
                <span style="display: inline-block; background: #1e293b; color: #a855f7; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">{role_type}</span>
                <span style="display: inline-block; background: #1e293b; color: #34d399; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">💼 {exp_badge}</span>
                {sal_badge}
                <span style="display: inline-block; background: #1e293b; color: #f472b6; padding: 3px 8px; border-radius: 4px; font-size: 11px; margin: 2px 5px 2px 0; vertical-align: middle;">{loc_mode_text}</span>
              </div>
              <div style="margin-top: 10px;">
                <a href="{url}" style="display: inline-block; background: #0284c7; color: #ffffff; padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; text-decoration: none;">
                  Apply Directly →
                </a>
              </div>
            </div>
            """

        # Build Recruiter Posts HTML
        posts_html = ""
        for post in valid_posts[:15]:
            poster = post.get("poster_name") or "HR / Recruiter"
            company = post.get("company") or "Organization"
            role = post.get("role_title") or "Hiring Opportunity"
            snippet = (post.get("post_text") or "")[:240] + ("..." if len(post.get("post_text") or "") > 240 else "")
            post_url = post.get("post_url") or "#"
            contact = post.get("contact_email") or post.get("contact_phone") or "Direct on LinkedIn"

            posts_html += f"""
            <div style="background: #0f172a; border: 1px solid #475569; border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; border-left: 4px solid #ec4899;">
              <div style="margin-bottom: 4px;">
                <span style="color: #ec4899; font-weight: bold; font-size: 12px;">📢 HR / Recruiter Post</span> • 
                <strong style="color: #f8fafc; font-size: 13px;">{poster}</strong> ({company})
              </div>
              <h4 style="margin: 4px 0 6px 0; font-size: 14px; color: #f1f5f9;">{role}</h4>
              <p style="font-size: 12px; color: #cbd5e1; background: #1e293b; padding: 8px 10px; border-radius: 6px; font-style: italic; margin: 6px 0;">
                "{snippet}"
              </p>
              <div style="font-size: 12px; color: #34d399; margin: 6px 0;">
                <strong>Contact / Info:</strong> {contact}
              </div>
              <div style="margin-top: 8px;">
                <a href="{post_url}" style="display: inline-block; background: #db2777; color: #ffffff; padding: 5px 12px; border-radius: 6px; font-size: 11px; font-weight: 600; text-decoration: none;">
                  View LinkedIn Post →
                </a>
              </div>
            </div>
            """

        from job_pulse.utils.time_utils import get_ist_display
        now_ist = get_ist_display()

        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0b1120; color: #f1f5f9; padding: 20px; }}
            .container {{ max-width: 660px; margin: 0 auto; background: #1e293b; border-radius: 12px; border: 1px solid #334155; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #ea580c, #0284c7); padding: 28px 24px; }}
            .header h1 {{ margin: 0; font-size: 22px; color: #ffffff; }}
            .header p {{ margin: 6px 0 0 0; color: #ffedd5; font-size: 13px; }}
            .metrics-pill-bar {{ display: flex; gap: 8px; margin: 16px 0 20px 0; flex-wrap: wrap; }}
            .pill {{ background: #0f172a; border: 1px solid #334155; padding: 6px 12px; border-radius: 6px; font-size: 12px; color: #f8fafc; }}
            .content {{ padding: 24px; }}
            .section-title {{ font-size: 15px; color: #f8fafc; font-weight: bold; margin: 22px 0 12px 0; border-bottom: 1px solid #334155; padding-bottom: 6px; }}
            .footer {{ padding: 16px 24px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #334155; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>🇮🇳 cMPLiBe AIScanner • All-India Opportunity Radar</h1>
              <p>Pan-India Real-Time Multi-Portal Job & Internship Intelligence</p>
            </div>
            <div class="content">
              <p style="margin-top: 0; font-size: 14px; color: #cbd5e1; line-height: 1.5;">
                cMPLiBe's AIScanner detected <strong>{total_items} newly posted openings & recruiter requirements</strong> across top Indian employment portals (Naukri, Indeed, Shine, LinkedIn, Foundit, Internshala, Unstop).
              </p>

              <div class="metrics-pill-bar">
                <div class="pill">📊 <strong>{total_items}</strong> Total New</div>
                <div class="pill">💻 <strong>{tech_count}</strong> Technical</div>
                <div class="pill">👔 <strong>{nontech_count}</strong> Non-Technical</div>
                {f'<div class="pill">🎓 <strong>{intern_count}</strong> Intern/Fresher</div>' if intern_count else ''}
                {f'<div class="pill">📢 <strong>{len(valid_posts)}</strong> HR Posts</div>' if valid_posts else ''}
              </div>

              {f'<div class="section-title">💼 Discovered Positions & Vacancies ({len(valid_jobs)})</div>' + jobs_html if valid_jobs else ''}
              {f'<div class="section-title">📢 Recruiter & HR Feed Posts ({len(valid_posts)})</div>' + posts_html if valid_posts else ''}

            </div>
            <div class="footer">
              Sent automatically by cMPLiBe AIScanner All-India Radar • Generated on {now_ist}
            </div>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_body, "html"))

        try:
            with cls._create_smtp_connection(config) as server:
                server.sendmail(sender, [recipient], msg.as_string())
            logger.info(f"Successfully emailed All-India radar alert ({total_items} items) to {recipient}")
            return True, f"Emailed {total_items} new All-India opportunity alert(s) to {recipient}"
        except Exception as e:
            logger.error(f"Failed to email All-India radar alert: {e}")
            return False, str(e)

