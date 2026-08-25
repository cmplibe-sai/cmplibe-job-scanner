import csv
import json
from pathlib import Path
from typing import List, Dict, Any
from job_pulse.models import JobPost


class JobExporter:
    """Exports scraped job posts into CSV, JSON, and Markdown formats."""

    @staticmethod
    def to_csv(jobs: List[Dict[str, Any]], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "title",
            "company",
            "role_type",
            "location",
            "work_mode",
            "experience_text",
            "salary_text",
            "skills",
            "url",
            "source_portal",
            "posted_date",
            "scraped_at",
        ]
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for j in jobs:
                row = dict(j)
                if not row.get("role_type"):
                    from job_pulse.models import classify_role_type
                    row["role_type"] = classify_role_type(row.get("title", "")).value
                elif hasattr(row.get("role_type"), "value"):
                    row["role_type"] = row["role_type"].value
                if isinstance(row.get("skills"), list):
                    row["skills"] = ", ".join(row["skills"])
                writer.writerow(row)
        return output_path

    @staticmethod
    def to_json(jobs: List[Dict[str, Any]], output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2, ensure_ascii=False)
        return output_path

    @staticmethod
    def to_markdown(jobs: List[Dict[str, Any]], output_path: Path, title: str = "Job Search Digest") -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# {title}", f"Total Jobs: **{len(jobs)}**\n", "---"]
        for j in jobs:
            skills = ", ".join(j.get("skills", [])) if isinstance(j.get("skills"), list) else ""
            lines.append(f"### [{j.get('title')}]({j.get('url')})")
            lines.append(f"- **Company:** {j.get('company')}")
            lines.append(f"- **Portal:** `{j.get('source_portal')}` | **Mode:** `{j.get('work_mode')}`")
            lines.append(f"- **Location:** {j.get('location')}")
            if j.get("experience_text"):
                lines.append(f"- **Experience:** {j.get('experience_text')}")
            if j.get("salary_text"):
                lines.append(f"- **Salary:** {j.get('salary_text')}")
            if skills:
                lines.append(f"- **Skills:** `{skills}`")
            lines.append("\n---\n")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return output_path
