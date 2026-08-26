"""
cMPLiBe AIScanner - Bee 🐝 AI Assistant Engine
Intelligent in-app conversational assistant for onboarding, feature guidance, role walkthroughs, and troubleshooting.
"""

from typing import Dict, Any, List, Optional
import re


class BeeAssistant:
    """
    Intelligent knowledge retrieval and conversational assistant for cMPLiBe AIScanner.
    Named 'Bee' 🐝 (Honeybee) - diligently searches through the entire documentation and delivers precise, actionable answers.
    """

    KNOWLEDGE_BASE = [
        {
            "id": "add_target_company",
            "keywords": ["add company", "add target", "target company", "new company", "track company", "watchlist", "missing company", "add targeted companies"],
            "title": "How to Add a New Target Company to Watchlist Radar",
            "summary": "You can add any company (e.g. Stripe, Swiggy, Zerodha, Jumbotail) to the 24/7 Target Company Radar in seconds.",
            "steps": [
                "1. Click the **Target Company Radar** tab in the top navigation bar.",
                "2. Click the green **'+ Add Target Company'** button.",
                "3. Enter the **Company Name** (e.g., *Jumbotail*, *Paytm*, *Razorpay*).",
                "4. *(Optional)* Provide their specific **Career Page URL** (e.g., `https://company.com/careers` or Greenhouse / Lever / Ashby link).",
                "5. Enter comma-separated role keywords to track (e.g., `developer, engineer, product, intern, analyst`).",
                "6. Select the monitoring channels: **ATS / Career Page**, **LinkedIn Recruiter Posts**, and **Multi-Portal Search**.",
                "7. Click **'Save & Start Radar Tracking'**. The AI Scanner will now continuously scan this company 24/7!"
            ],
            "action": {"tab": "radar", "label": "Go to Target Company Radar"},
            "role": "all",
        },
        {
            "id": "search_opportunities",
            "keywords": ["search", "find jobs", "how to search", "filter", "technical", "non-technical", "freshers", "internships", "explorer"],
            "title": "How to Search & Explore Opportunities Across 9+ Portals",
            "summary": "Search live job openings across LinkedIn, Naukri, Foundit, Internshala, Unstop, Shine, and LinkedIn Recruiter Posts.",
            "steps": [
                "1. Open the **Opportunity Explorer** tab.",
                "2. Choose your search mode: **'By Role / Title'** or **'By Company'**.",
                "3. Type your keywords (e.g., `Category Manager`, `HR Recruiter`, `Python Backend`, `React`) or click a Quick Category Preset (*Tech*, *Non-Tech*, *Internships*, *Growth*).",
                "4. Select your target **Location** (e.g., `All India`, `Bangalore`, `Mumbai`, `Delhi-NCR`, `Remote`).",
                "5. Choose which job portals to scrape (LinkedIn, Internshala, Unstop, Shine, Naukri, Foundit, Indeed).",
                "6. Click **'Scan Portals Now'**. Results will stream in real-time, deduplicated and classified into Technical / Non-Technical roles!"
            ],
            "action": {"tab": "explorer", "label": "Go to Opportunity Explorer"},
            "role": "all",
        },
        {
            "id": "all_india_radar",
            "keywords": ["all india", "all-india", "discovery", "broad scan", "nationwide", "multi portal radar", "radar 2"],
            "title": "Understanding the All-India Multi-Portal Discovery Radar (Radar 2)",
            "summary": "Radar 2 scans across the entire country for broad job discoveries across all major portals and delivers alerts directly to your inbox.",
            "steps": [
                "1. Click the **All-India Job Radar 🇮🇳** tab.",
                "2. It monitors high-demand roles across Bangalore, Mumbai, Delhi-NCR, Hyderabad, Pune, Chennai, and Remote.",
                "3. You can filter between **All Roles**, **Technical Roles Only**, or **Non-Technical Roles Only**.",
                "4. Click **'Run All-India Discovery Scan Now'** to trigger an immediate multi-portal discovery scan.",
                "5. Emailed alerts will automatically deliver newly discovered positions to your configured recipient email!"
            ],
            "action": {"tab": "discovery", "label": "Open All-India Radar"},
            "role": "all",
        },
        {
            "id": "google_sheets_sync",
            "keywords": ["google sheet", "google sheets", "sheets sync", "spreadsheet", "export to sheet", "live sync", "sheets automation"],
            "title": "How Google Sheets Live Sync Works",
            "summary": "Automatically syncs every scraped job, radar alert, and recruiter post directly into Google Sheets in real-time.",
            "steps": [
                "1. Click the **Google Sheet Live Sync 📊** tab.",
                "2. The system automatically syncs to the designated spreadsheet with three organized tabs: **'All-India Jobs'**, **'Target Company Radar'**, and **'Recruiter Posts'**.",
                "3. Each row includes Job Title, Company, Work Mode, Location, Category, Role Type, Portal Source, Direct Application URL, and Scraped Timestamp in IST.",
                "4. Click **'Sync Live Database to Google Sheets'** to perform an immediate sync.",
                "5. Click **'Clean Junk Links from Google Sheet'** to automatically purge any non-job navigation links."
            ],
            "action": {"tab": "sheets", "label": "Open Google Sheets Sync"},
            "role": "all",
        },
        {
            "id": "email_alerts_setup",
            "keywords": ["email alert", "mail settings", "smtp", "resend", "notifications", "recipient email", "configure email", "no email", "not receiving email"],
            "title": "Configuring 24/7 Automated Email Alerts & Resend API",
            "summary": "Configure dual-channel email alerts powered by the Resend HTTPS API (Port 443) for 100% cloud-reliable delivery.",
            "steps": [
                "1. Go to **Email & System Settings ⚙️** (Admin only).",
                "2. Click the **⚡ Resend HTTPS API (Recommended for Cloud — Port 443)** preset button.",
                "3. Enter your Resend API Key in the Password field.",
                "4. Set the **Sender Email Header** to `cMPLiBe AIScanner <alerts@cmplibe.com>`.",
                "5. Enter the **Target Radar Recipient Email** (e.g. `earlitalent@cmplibe.com`) and **All-India Recipient Email**.",
                "6. Click **Step 1: Test Mail Server Connection** to verify.",
                "7. Click **Step 2: Test Send Target Radar Email** to test delivery.",
                "8. Click **Step 3: Save System & Email Settings** to activate 24/7 automated alerts!"
            ],
            "action": {"tab": "settings", "label": "Open Email Settings"},
            "role": "admin",
        },
        {
            "id": "user_management",
            "keywords": ["add user", "create user", "team members", "roles", "admin vs member", "invite member", "password reset"],
            "title": "Managing Team Members & Role Permissions",
            "summary": "Administrators can add team members, assign roles (Admin vs Member), and manage security.",
            "steps": [
                "1. Log in as an **Admin** user and open **Email & System Settings ⚙️**.",
                "2. Scroll down to the **'Team Access & Member Management'** section.",
                "3. In the **'Add New Team Member'** box, enter a unique Username, temporary Password, and select Role (**Member** or **Admin**).",
                "4. Click **'Create Member Account'**.",
                "5. **Admin Role**: Has full access to SMTP credentials, Google Sheets credentials, team creation, and interval controls.",
                "6. **Member Role**: Has a streamlined interface for searching opportunities, adding target companies, running scans, and viewing sheets without seeing sensitive backend passwords."
            ],
            "action": {"tab": "settings", "label": "Open Team Management"},
            "role": "admin",
        },
        {
            "id": "admin_vs_member_difference",
            "keywords": ["difference", "admin", "member", "permissions", "user vs admin", "what can member do", "what can admin do"],
            "title": "Differences Between Admin and Team Member Roles",
            "summary": "Clear separation of duties between Administrators and Team Members for team security and ease of use.",
            "steps": [
                "👑 **Administrator Capabilities:**",
                " • Manage Outgoing Mail Server (SMTP / Resend API Keys & Port settings).",
                " • Configure Google Sheets service account credentials and spreadsheet ID.",
                " • Create and deactivate Team Member accounts and reset passwords.",
                " • Configure background scan frequency intervals (15m, 30m, 60m, 120m).",
                "👤 **Team Member Capabilities:**",
                " • Explore & filter live opportunities across 9+ portals with custom keywords.",
                " • Add new watched target companies to the Watchlist Radar.",
                " • Run instant scans on watched companies or All-India multi-portal discovery.",
                " • Trigger immediate Google Sheets sync and view synced worksheets.",
                " • Access this documentation guide and the Bee 🐝 AI Assistant 24/7."
            ],
            "action": {"tab": "docs", "label": "View Full Role Guide"},
            "role": "all",
        },
        {
            "id": "hostinger_persistence",
            "keywords": ["render sleep", "disconnected", "erased", "hostinger", "24/7 hosting", "server restart", "data deleted", "stay active"],
            "title": "Why Render Sleeps & How Hostinger Keeps the System 24/7",
            "summary": "Explanation of Render's free tier sleep behavior versus persistent hosting on Hostinger.",
            "steps": [
                "• **Why Render Disconnects**: Render Free Tier spins down (sleeps) after 15 minutes of inactivity. When it restarts, it uses a fresh temporary container that resets in-memory data and pauses background cron alerts.",
                "• **Why Hostinger is 100% Reliable**: Hostinger (VPS / Python Hosting) provides dedicated 24/7 compute with permanent SSD storage. The SQLite database is never wiped, and background scans run continuously even when your laptop is turned off.",
                "• Check the provided **Hostinger Deployment Guide** in the project repository for simple 1-command deployment instructions!"
            ],
            "action": {"tab": "docs", "label": "Open Playbook Guide"},
            "role": "all",
        }
    ]

    QUICK_PROMPTS = [
        "How do I add a new target company?",
        "How to search opportunities across portals?",
        "How does Google Sheets Live Sync work?",
        "What is the difference between Admin and Member?",
        "How do I set up email alerts?",
        "Why did my alerts pause on Render?",
    ]

    @classmethod
    def answer_question(cls, query: str, user_role: str = "member") -> Dict[str, Any]:
        """
        Process a user question, retrieve relevant knowledge items, and return structured conversational response.
        """
        q_clean = (query or "").strip().lower()
        if not q_clean:
            return {
                "reply": "Hello! I am **Bee** 🐝, your cMPLiBe AI Assistant! Ask me anything about adding companies, searching opportunities, email alerts, Google Sheets sync, or user roles.",
                "suggestions": cls.QUICK_PROMPTS[:4],
                "action": None,
            }

        # Friendly greeting check
        greetings = ["hi", "hello", "hey", "who are you", "what can you do", "help", "namaste"]
        if q_clean in greetings or any(q_clean.startswith(g + " ") for g in greetings):
            role_desc = "an **Administrator** (full access)" if user_role == "admin" else "a **Team Member**"
            return {
                "reply": f"Bzz! 🐝 Hello there! I am **Bee**, your diligent cMPLiBe AI Assistant. You are currently logged in as {role_desc}.\n\nHow can I help you today? You can ask me how to add target companies, search multi-portal jobs, sync to Google Sheets, or manage settings!",
                "suggestions": cls.QUICK_PROMPTS[:4],
                "action": {"tab": "docs", "label": "Open Documentation Center"},
            }

        # Keyword scoring algorithm
        best_match = None
        best_score = 0

        for item in cls.KNOWLEDGE_BASE:
            score = 0
            # Check keywords
            for kw in item["keywords"]:
                if kw in q_clean:
                    score += 5
                elif any(word in q_clean for word in kw.split() if len(word) > 3):
                    score += 2

            # Check title
            for word in item["title"].lower().split():
                if len(word) > 3 and word in q_clean:
                    score += 3

            # Check summary
            for word in item["summary"].lower().split():
                if len(word) > 4 and word in q_clean:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = item

        if best_match and best_score >= 3:
            steps_md = "\n".join(best_match["steps"])
            reply_text = f"### 🐝 {best_match['title']}\n\n{best_match['summary']}\n\n**Step-by-Step Instructions:**\n{steps_md}"
            
            if best_match.get("role") == "admin" and user_role != "admin":
                reply_text += "\n\n> ℹ️ **Note:** This feature contains settings restricted to **Administrators**. Regular team members have simplified view access."

            # Related suggestion generation
            other_suggestions = [k["title"] for k in cls.KNOWLEDGE_BASE if k["id"] != best_match["id"]][:3]

            return {
                "reply": reply_text,
                "suggestions": other_suggestions,
                "action": best_match.get("action"),
            }

        # Fallback intelligent answer
        return {
            "reply": (
                "Bzz! 🐝 I searched everywhere in our system documentation, but couldn't find an exact match for your question.\n\n"
                "Here are some helpful things you can ask me:\n"
                "• *'How do I add a new company to the watchlist?'*\n"
                "• *'How do I search for technical vs non-technical roles?'*\n"
                "• *'How does Google Sheets Sync work?'*\n"
                "• *'What is the difference between Admin and Member?'*\n"
                "• *'How do I configure email alerts?'*"
            ),
            "suggestions": cls.QUICK_PROMPTS[:4],
            "action": {"tab": "docs", "label": "Browse Full Playbook Guide"},
        }
