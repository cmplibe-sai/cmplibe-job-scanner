import argparse
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from job_pulse.models import SearchQuery
from job_pulse.orchestrator import ScraperOrchestrator
from job_pulse.storage.db import JobDatabase
from job_pulse.pipeline.exporter import JobExporter
from job_pulse.scrapers.career_pages import CareerPageScraper

console = Console(highlight=False)


def cmd_search(args):
    """Execute live multi-portal scraping with recruiter posts."""
    portals = [p.strip().lower() for p in args.portals.split(",") if p.strip()]
    career_urls = [u.strip() for u in args.career_urls.split(",") if u.strip()] if args.career_urls else []

    if args.posts and "linkedin_posts" not in portals:
        portals.append("linkedin_posts")

    query = SearchQuery(
        keywords=args.keywords,
        location=args.location or "",
        company_name=args.company if hasattr(args, "company") else None,
        search_type="company" if args.by_company else "role",
        experience_level=args.experience if hasattr(args, "experience") else None,
        internship_only=args.internship,
        remote_only=args.remote,
        limit=args.limit,
        portals=portals,
        career_urls=career_urls,
        include_linkedin_posts="linkedin_posts" in portals,
    )

    console.print(
        Panel.fit(
            f"[bold cyan]cMPLiBe's AIScanner - Multi-Portal & Recruiter Post Aggregator[/bold cyan]\n"
            f"Search: [yellow]{query.keywords}[/yellow] (Mode: [bold]{query.search_type}[/bold]) | Location: [yellow]{query.location or 'All'}[/yellow] | Remote: [green]{query.remote_only}[/green]\n"
            f"Target Portals & Feeds: [magenta]{', '.join(query.portals)}[/magenta]"
            + (f"\nCareer URLs: [blue]{', '.join(query.career_urls)}[/blue]" if query.career_urls else ""),
            border_style="cyan",
        )
    )

    orchestrator = ScraperOrchestrator()

    with Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Scraping job portals and recruiter posts in parallel...", total=None)
        res = orchestrator.run(query)
        progress.update(task, completed=True)

    console.print(f"\n[bold green]✓ Scraping Complete![/bold green] Portal Jobs: [cyan]{res['total_scraped']}[/cyan] | Recruiter Posts: [magenta]{res.get('total_hiring_posts', 0)}[/magenta] | Unique Jobs: [green]{res['unique_jobs']}[/green] in {res['execution_time_seconds']}s\n")

    # Portal Summary Table
    summary_table = Table(title="Scraping Results by Source", header_style="bold magenta")
    summary_table.add_column("Channel / Portal", style="bold")
    summary_table.add_column("Status", justify="center")
    summary_table.add_column("Found", justify="right")
    summary_table.add_column("Time (s)", justify="right")
    summary_table.add_column("Note / Error")

    for p_name, p_res in res["portal_results"].items():
        cnt = p_res.total_found
        status_badge = "[green]Success[/green]" if p_res.success and cnt > 0 else "[yellow]0 Results[/yellow]" if p_res.success else "[red]Failed[/red]"
        summary_table.add_row(
            p_res.portal,
            status_badge,
            str(cnt),
            str(p_res.execution_time_seconds),
            p_res.error_message or "-"
        )
    console.print(summary_table)

    # Discovered Jobs Table
    if res["jobs"]:
        job_table = Table(title=f"Sample Discovered Opportunities ({min(12, len(res['jobs']))} of {len(res['jobs'])})", header_style="bold blue")
        job_table.add_column("Title", style="bold white", max_width=35)
        job_table.add_column("Company", style="cyan", max_width=25)
        job_table.add_column("Portal", style="magenta")
        job_table.add_column("Location", style="dim", max_width=20)
        job_table.add_column("Mode", style="green")
        job_table.add_column("Exp / Sal", style="yellow")
        job_table.add_column("Apply Link", style="blue underline", max_width=30)

        for j in res["jobs"][:12]:
            sal_exp = j.get("salary_text") or j.get("experience_text") or ("Internship" if j.get("is_internship") else "-")
            job_table.add_row(
                j.get("title", "")[:35],
                j.get("company", "")[:25],
                j.get("source_portal", ""),
                j.get("location", "")[:20],
                j.get("work_mode", "Unknown"),
                sal_exp[:20],
                j.get("url", "")[:30] + "...",
            )
        console.print(job_table)

    # Recruiter Hiring Posts Table
    if res.get("hiring_posts"):
        posts_table = Table(title=f"Sample Recruiter & HR Posts ({min(8, len(res['hiring_posts']))} of {len(res['hiring_posts'])})", header_style="bold magenta")
        posts_table.add_column("Poster / HR", style="bold white", max_width=25)
        posts_table.add_column("Role / Requirements", style="cyan", max_width=30)
        posts_table.add_column("Contact Email / Phone", style="green", max_width=25)
        posts_table.add_column("Post Link", style="blue underline", max_width=30)

        for p in res["hiring_posts"][:8]:
            contact = p.get("contact_email") or p.get("contact_phone") or "Via LinkedIn"
            posts_table.add_row(
                p.get("poster_name", "Recruiter")[:25],
                p.get("role_title", "")[:30],
                contact[:25],
                p.get("post_url", "")[:30] + "...",
            )
        console.print(posts_table)

    # Auto export if requested
    if args.export:
        out_path = Path(args.export)
        if out_path.suffix.lower() == ".csv":
            JobExporter.to_csv(res["jobs"], out_path)
        elif out_path.suffix.lower() == ".json":
            JobExporter.to_json(res["jobs"], out_path)
        else:
            JobExporter.to_markdown(res["jobs"], out_path)
        console.print(f"[bold green]✓ Exported to {out_path.resolve()}[/bold green]")


def cmd_ats(args):
    """Scrape a direct ATS / career page URL."""
    console.print(f"[bold cyan]Scraping Career Page / ATS URL:[/bold cyan] {args.url}")
    scraper = CareerPageScraper()
    with console.status("[bold green]Fetching openings from career page..."):
        jobs = scraper.scrape_url(args.url, keyword_filter=args.filter or "", company_override=args.company or "")

    if not jobs:
        console.print("[yellow]No jobs found on the specified career page.[/yellow]")
        return

    table = Table(title=f"Discovered Roles on {args.url} ({len(jobs)} total)", header_style="bold green")
    table.add_column("Title", style="bold white")
    table.add_column("Company", style="cyan")
    table.add_column("Location", style="dim")
    table.add_column("Mode", style="magenta")
    table.add_column("Apply Link", style="blue underline")

    for j in jobs[:25]:
        table.add_row(j.title, j.company, j.location, str(j.work_mode), j.url)
    console.print(table)

    db = JobDatabase()
    saved = db.save_jobs_batch(jobs)
    console.print(f"[bold green]✓ Saved {saved} new jobs to database.[/bold green]")


def cmd_list(args):
    """List jobs stored in local database."""
    db = JobDatabase()
    jobs = db.get_jobs(
        keywords=args.query,
        location=args.location,
        company=args.company,
        portal=args.portal,
        work_mode=args.mode,
        experience_level=args.experience,
        is_internship=args.internship,
        limit=args.limit,
    )

    if not jobs:
        console.print("[yellow]No jobs found in database matching criteria.[/yellow]")
        return

    table = Table(title=f"Stored Jobs ({len(jobs)} listings)", header_style="bold cyan")
    table.add_column("Title", style="bold white", max_width=35)
    table.add_column("Company", style="cyan", max_width=25)
    table.add_column("Portal", style="magenta")
    table.add_column("Location", style="dim", max_width=20)
    table.add_column("Mode", style="green")
    table.add_column("Exp / Sal", style="yellow", max_width=20)
    table.add_column("Apply Link", style="blue underline")

    for j in jobs:
        sal_exp = j.get("salary_text") or j.get("experience_text") or ("Internship" if j.get("is_internship") else "")
        table.add_row(
            j.get("title", "")[:35],
            j.get("company", "")[:25],
            j.get("source_portal", ""),
            j.get("location", "")[:20],
            j.get("work_mode", ""),
            sal_exp[:20],
            j.get("url", "")[:35] + "...",
        )
    console.print(table)


def cmd_posts(args):
    """List stored recruiter & HR hiring posts."""
    db = JobDatabase()
    posts = db.get_hiring_posts(
        keywords=args.query,
        location=args.location,
        company=args.company,
        limit=args.limit,
    )

    if not posts:
        console.print("[yellow]No hiring posts found in database.[/yellow]")
        return

    table = Table(title=f"Stored Recruiter & HR Posts ({len(posts)} posts)", header_style="bold magenta")
    table.add_column("Poster / HR", style="bold white", max_width=25)
    table.add_column("Role", style="cyan", max_width=25)
    table.add_column("Post Snippet", style="dim", max_width=45)
    table.add_column("Contact", style="green", max_width=25)
    table.add_column("Post URL", style="blue underline")

    for p in posts:
        contact = p.get("contact_email") or p.get("contact_phone") or "LinkedIn Post"
        table.add_row(
            p.get("poster_name", "")[:25],
            p.get("role_title", "")[:25],
            p.get("post_text", "")[:45] + "...",
            contact[:25],
            p.get("post_url", "")[:35] + "...",
        )
    console.print(table)


def cmd_stats(args):
    """Display database statistics."""
    db = JobDatabase()
    stats = db.get_stats()
    console.print(Panel.fit(
        f"[bold cyan]cMPLiBe's AIScanner Database Statistics[/bold cyan]\n\n"
        f"Total Jobs Stored: [bold green]{stats['total_jobs']}[/bold green]\n"
        f"Recruiter Hiring Posts: [bold magenta]{stats.get('total_hiring_posts', 0)}[/bold magenta]\n"
        f"Unique Companies: [bold yellow]{stats['total_companies']}[/bold yellow]\n\n"
        f"[bold]By Portal:[/bold]\n" + "\n".join([f"  • {k}: [cyan]{v}[/cyan]" for k, v in stats['portal_breakdown'].items()]) + "\n\n"
        f"[bold]By Work Mode:[/bold]\n" + "\n".join([f"  • {k}: [magenta]{v}[/magenta]" for k, v in stats['work_mode_breakdown'].items()]),
        border_style="green",
    ))


def cmd_export(args):
    """Export database jobs to CSV/JSON/MD."""
    db = JobDatabase()
    jobs = db.get_jobs(limit=10000)
    out_path = Path(args.output)
    if args.format == "csv" or out_path.suffix == ".csv":
        JobExporter.to_csv(jobs, out_path)
    elif args.format == "json" or out_path.suffix == ".json":
        JobExporter.to_json(jobs, out_path)
    else:
        JobExporter.to_markdown(jobs, out_path)
    console.print(f"[bold green]✓ Successfully exported {len(jobs)} jobs to {out_path.resolve()}[/bold green]")


def cmd_discovery(args):
    """Trigger All-India Multi-Portal Opportunity Radar scan."""
    from job_pulse.radar.discovery_scanner import AllIndiaDiscoveryScanner
    scanner = AllIndiaDiscoveryScanner()
    console.print(
        Panel.fit(
            f"[bold orange3]🇮🇳 cMPLiBe AIScanner - All-India Opportunity Radar[/bold orange3]\n"
            f"Keywords: [yellow]{args.keywords or 'Broad Default Roles'}[/yellow] | Hubs: [yellow]{args.location}[/yellow] | Email Alert: [green]{not args.no_email}[/green] | Google Sheets: [green]{not args.no_sheets}[/green]",
            border_style="orange3",
        )
    )

    with Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Scanning pan-India opportunities across portals...", total=None)
        res = scanner.scan_all_india(
            keywords=args.keywords,
            location=args.location,
            role_type=args.role_type,
            experience_level=args.experience or None,
            send_email=not args.no_email,
            sync_sheets=not args.no_sheets,
        )
        progress.update(task, completed=True)

    console.print(f"\n[bold green]✓ All-India Radar Scan Complete![/bold green] Total Scraped: [cyan]{res['total_scraped']}[/cyan] | Unique Jobs: [green]{res['unique_jobs']}[/green] | New Stored: [yellow]{res['new_stored']}[/yellow] in {res['execution_time_seconds']}s")
    console.print(f"📧 Email Status: [magenta]{res['email_status']}[/magenta]")
    console.print(f"📊 Google Sheets: [blue]{res['sheets_status']}[/blue]\n")


def cmd_sheets(args):
    """Manage Google Sheets live synchronization."""
    from job_pulse.pipeline.sheets_sync import GoogleSheetsManager
    db = JobDatabase()
    sheets_config = db.get_sheets_config()

    if args.action == "test":
        console.print("[cyan]Testing Google Sheets connection...[/cyan]")
        success, msg = GoogleSheetsManager.test_connection(sheets_config)
        if success:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")
    elif args.action == "clean":
        console.print("[cyan]Scanning and cleaning non-job rows from Google Sheets...[/cyan]")
        success, cnt, msg = GoogleSheetsManager.clean_worksheet_junk_rows(sheets_config)
        if success:
            console.print(f"[bold green]✓ {msg}[/bold green]")
        else:
            console.print(f"[bold red]✗ {msg}[/bold red]")
    elif args.action == "sync":
        console.print("[cyan]Synchronizing stored opportunities to Google Sheets...[/cyan]")
        jobs = db.get_jobs(limit=args.limit)
        posts = db.get_hiring_posts(limit=args.limit)
        ok_j, cnt_j, msg_j = GoogleSheetsManager.sync_jobs(jobs, sheets_config)
        ok_p, cnt_p, msg_p = GoogleSheetsManager.sync_hiring_posts(posts, sheets_config)
        total = cnt_j + cnt_p
        if total > 0:
            db.update_sheets_sync_stats(total)
        console.print(f"[bold green]✓ Synced {cnt_j} jobs and {cnt_p} recruiter posts to Google Sheets.[/bold green]")
    else:
        console.print(Panel.fit(
            f"[bold cyan]Google Sheets Live Sync Status[/bold cyan]\n"
            f"Enabled: [bold]{sheets_config.get('is_enabled')}[/bold]\n"
            f"Spreadsheet ID / URL: [yellow]{sheets_config.get('spreadsheet_id_or_url') or 'Not configured'}[/yellow]\n"
            f"All-India Worksheet: [magenta]{sheets_config.get('sheet_name_all_india')}[/magenta]\n"
            f"Target Radar Worksheet: [magenta]{sheets_config.get('sheet_name_target_radar')}[/magenta]\n"
            f"Last Synced: [green]{sheets_config.get('last_synced_at') or 'Never'}[/green] ({sheets_config.get('last_synced_count', 0)} rows)",
            border_style="green",
        ))


def cmd_serve(args):
    """Launch the Web Dashboard server."""
    import uvicorn
    console.print(f"[bold green]Starting cMPLiBe's AIScanner Web Dashboard on http://{args.host}:{args.port}[/bold green]")
    uvicorn.run("job_pulse.server:app", host=args.host, port=args.port, reload=args.reload)


def main():
    parser = argparse.ArgumentParser(description="cMPLiBe's AIScanner - Multi-Portal Job & Recruiter Post CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Search Command
    p_search = subparsers.add_parser("search", help="Scrape live jobs and recruiter posts")
    p_search.add_argument("keywords", type=str, help="Search keywords (e.g. 'Category Manager', 'HR Recruiter', 'Python')")
    p_search.add_argument("--location", "-l", type=str, default="", help="City / Location (e.g. 'Bangalore', 'Mumbai', 'Remote')")
    p_search.add_argument("--company", "-c", type=str, default="", help="Filter by specific company name")
    p_search.add_argument("--by-company", action="store_true", help="Treat search keywords as company name")
    p_search.add_argument("--role-type", "-t", choices=["all", "technical", "non_technical"], default="all", help="Filter by Technical vs Non-Technical")
    p_search.add_argument("--experience", "-x", type=str, default="", choices=["", "internship", "0-2", "3-5", "6-10", "10+"], help="Experience level")
    p_search.add_argument("--internship", action="store_true", help="Filter for internships only")
    p_search.add_argument("--posts", action="store_true", help="Include LinkedIn recruiter & hiring manager feed posts")
    p_search.add_argument("--portals", "-p", type=str, default="linkedin,internshala,unstop,shine,naukri,foundit,indeed,linkedin_posts", help="Comma-separated portals")
    p_search.add_argument("--career-urls", "-u", type=str, default="", help="Comma-separated company career or ATS URLs (e.g. https://jumbotail.com/careers/)")
    p_search.add_argument("--remote", "-r", action="store_true", help="Filter for remote jobs only")
    p_search.add_argument("--limit", type=int, default=50, help="Max jobs to scrape per source")
    p_search.add_argument("--export", "-e", type=str, default="", help="Filepath to export results (e.g. jobs.csv)")
    p_search.set_defaults(func=cmd_search)

    # All-India Discovery Radar Command
    p_disc = subparsers.add_parser("discovery", help="Run All-India Opportunity Discovery Radar")
    p_disc.add_argument("--keywords", "-k", type=str, default="", help="Custom role search keywords")
    p_disc.add_argument("--location", "-l", type=str, default="India", help="Target Indian city or 'India'")
    p_disc.add_argument("--role-type", "-t", choices=["all", "technical", "non_technical"], default="all", help="Filter role type")
    p_disc.add_argument("--experience", "-x", type=str, default="", choices=["", "internship", "0-2", "3-5", "6-10", "10+"], help="Experience level")
    p_disc.add_argument("--no-email", action="store_true", help="Do not dispatch email alert")
    p_disc.add_argument("--no-sheets", action="store_true", help="Do not sync to Google Sheets")
    p_disc.set_defaults(func=cmd_discovery)

    # Google Sheets Command
    p_sheets = subparsers.add_parser("sheets", help="Google Sheets synchronization")
    p_sheets.add_argument("action", choices=["status", "test", "sync", "clean"], default="status", nargs="?", help="Action to perform")
    p_sheets.add_argument("--limit", type=int, default=1000, help="Max jobs to sync")
    p_sheets.set_defaults(func=cmd_sheets)

    # ATS / Career Page Command
    p_ats = subparsers.add_parser("ats", help="Scrape direct company ATS or career page link")
    p_ats.add_argument("url", type=str, help="Career page URL (e.g. https://jumbotail.com/careers/ or Greenhouse/Lever)")
    p_ats.add_argument("--company", "-c", type=str, default="", help="Company name override")
    p_ats.add_argument("--filter", "-f", type=str, default="", help="Keyword filter for roles")
    p_ats.set_defaults(func=cmd_ats)

    # List Command
    p_list = subparsers.add_parser("list", help="List stored jobs in database")
    p_list.add_argument("--query", "-q", type=str, default="", help="Filter stored jobs by text")
    p_list.add_argument("--company", "-c", type=str, default="", help="Filter by company")
    p_list.add_argument("--location", "-l", type=str, default="", help="Filter by location")
    p_list.add_argument("--portal", "-p", type=str, default="", help="Filter by portal")
    p_list.add_argument("--mode", "-m", type=str, default="", help="Filter by work mode")
    p_list.add_argument("--experience", "-x", type=str, default="", help="Filter by experience level")
    p_list.add_argument("--internship", action="store_true", help="Filter for internships only")
    p_list.add_argument("--limit", type=int, default=50, help="Max items to list")
    p_list.set_defaults(func=cmd_list)

    # Posts Command
    p_posts = subparsers.add_parser("posts", help="List stored recruiter & HR hiring posts")
    p_posts.add_argument("--query", "-q", type=str, default="", help="Filter posts by text")
    p_posts.add_argument("--company", "-c", type=str, default="", help="Filter posts by company")
    p_posts.add_argument("--location", "-l", type=str, default="", help="Filter posts by location")
    p_posts.add_argument("--limit", type=int, default=50, help="Max posts to list")
    p_posts.set_defaults(func=cmd_posts)

    # Stats Command
    p_stats = subparsers.add_parser("stats", help="Show database job statistics")
    p_stats.set_defaults(func=cmd_stats)

    # Export Command
    p_export = subparsers.add_parser("export", help="Export stored jobs")
    p_export.add_argument("--output", "-o", type=str, default="data/exported_jobs.csv", help="Output file path")
    p_export.add_argument("--format", "-f", choices=["csv", "json", "md"], default="csv", help="Export format")
    p_export.set_defaults(func=cmd_export)

    # Serve Command
    p_serve = subparsers.add_parser("serve", help="Launch FastAPI Web Dashboard")
    p_serve.add_argument("--host", type=str, default="127.0.0.1", help="Host address")
    p_serve.add_argument("--port", type=int, default=8000, help="Port number")
    p_serve.add_argument("--reload", action="store_true", help="Auto-reload on code change")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()

