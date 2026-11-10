from __future__ import annotations

import argparse
from html import escape
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "portfolio/config.json"
STATE = ROOT / "portfolio/repositories.json"
PROJECTS = ROOT / "portfolio/projects.json"
DATA = ROOT / "portfolio/data.json"
README = ROOT / "README.md"

START = "<!-- REPOSITORIES_START -->"
END = "<!-- REPOSITORIES_END -->"
FEATURE_START = "<!-- FEATURED_PROJECTS_START -->"
FEATURE_END = "<!-- FEATURED_PROJECTS_END -->"
STATS_START = "<!-- GITHUB_STATS_START -->"
STATS_END = "<!-- GITHUB_STATS_END -->"
STACK_START = "<!-- TECHNOLOGY_STACK_START -->"
STACK_END = "<!-- TECHNOLOGY_STACK_END -->"
LINKS_START = "<!-- PROFILE_LINKS_START -->"
LINKS_END = "<!-- PROFILE_LINKS_END -->"
SKILLS_START = "<!-- SKILLS_START -->"
SKILLS_END = "<!-- SKILLS_END -->"
NAME_START = "<!-- PROFILE_NAME_START -->"
NAME_END = "<!-- PROFILE_NAME_END -->"
TITLE_START = "<!-- PROFILE_TITLE_START -->"
TITLE_END = "<!-- PROFILE_TITLE_END -->"
INTRO_START = "<!-- PROFILE_INTRO_START -->"
INTRO_END = "<!-- PROFILE_INTRO_END -->"
ABOUT_START = "<!-- ABOUT_START -->"
ABOUT_END = "<!-- ABOUT_END -->"


class GitHubCommandError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def save_json(path: Path, data: dict) -> None:
    rendered = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != rendered:
        path.write_text(rendered, encoding="utf-8")


def _raise_gh_error(result: subprocess.CompletedProcess[str], context: str) -> None:
    error = result.stderr.strip() or result.stdout.strip() or "unknown gh error"
    if "rate limit" in error.lower():
        raise GitHubCommandError(
            f"{context}: GitHub API rate limit reached. Retry after the limit "
            "resets or authenticate gh with an authorized account."
        )
    raise GitHubCommandError(f"{context}: {error}")


def gh_json(endpoint: str, *, allow_missing: bool = False):
    result = subprocess.run(
        ["gh", "api", endpoint, "--jq", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        error = (result.stderr + result.stdout).lower()
        if allow_missing and ("http 404" in error or "not found" in error):
            return None
        _raise_gh_error(result, f"GitHub API request failed for {endpoint}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GitHubCommandError(
            f"GitHub API returned invalid JSON for {endpoint}: {error}"
        ) from error


def discover(config: dict) -> list[dict]:
    username = config["username"]
    query = (
        f"users/{username}/repos?type=owner&visibility=public&per_page=100"
    )
    jq = (
        ".[] | {id,name,full_name,html_url,description,language,topics,"
        "created_at,updated_at,pushed_at,stargazers_count,forks_count,fork,"
        "archived,private,visibility,default_branch,size,open_issues_count}"
    )
    result = subprocess.run(
        ["gh", "api", "--paginate", query, "--jq", jq],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        _raise_gh_error(result, f"Could not discover public repositories for {username}")

    excluded = set(config.get("exclude_repositories", []))
    repos = []
    seen_ids = set()
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            repo = json.loads(line)
        except json.JSONDecodeError as error:
            raise GitHubCommandError(
                f"GitHub returned an invalid repository record: {error}"
            ) from error

        if repo.get("private") is not False:
            continue
        if repo.get("visibility") not in (None, "public"):
            continue
        if repo.get("name") in excluded:
            continue
        if not config.get("include_forks", True) and repo.get("fork"):
            continue
        if not config.get("include_archived", True) and repo.get("archived"):
            continue
        if repo.get("id") in seen_ids:
            continue
        seen_ids.add(repo.get("id"))
        repos.append(repo)

    return sorted(repos, key=lambda repo: repo.get("name", "").casefold())


def collect_repository_details(repos: list[dict]) -> None:
    for repo in repos:
        full_name = repo.get("full_name") or repo["name"]
        language_map = gh_json(
            f"repos/{full_name}/languages", allow_missing=True
        )
        repo["languages"] = (
            language_map if isinstance(language_map, dict) else {}
        )
        repo["readme"] = gh_json(
            f"repos/{full_name}/readme", allow_missing=True
        )


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _recently_created(repo: dict, now: datetime, duration: timedelta) -> bool:
    created = _parse_timestamp(repo.get("created_at"))
    return created is not None and timedelta(0) <= now - created < duration


def update_repository_state(
    repos: list[dict],
    state: dict,
    config: dict,
    now: datetime,
) -> None:
    duration = timedelta(days=max(0, config.get("new_badge_days", 14)))
    id_to_name = {
        str(record["repository_id"]): name
        for name, record in state.items()
        if record.get("repository_id") is not None
    }

    for repo in repos:
        name = repo["name"]
        repository_id = repo.get("id")
        previous_name = (
            id_to_name.get(str(repository_id))
            if repository_id is not None
            else None
        )
        record = state.get(name)

        if record is None and previous_name is not None:
            record = state.pop(previous_name)
            state[name] = record

        if record is None:
            baseline = bool(config.get("initialize_baseline", False))
            if not baseline:
                baseline = not _recently_created(repo, now, duration)
            record = {
                "first_seen": now.isoformat(),
                "baseline": baseline,
            }
            state[name] = record

        if repository_id is not None:
            record["repository_id"] = repository_id


def _new_badge(repo: dict, record: dict, now: datetime, duration: timedelta) -> bool:
    if record.get("baseline", False):
        return False
    first_seen = _parse_timestamp(record.get("first_seen"))
    created = _parse_timestamp(repo.get("created_at"))
    return (
        first_seen is not None
        and created is not None
        and timedelta(0) <= now - first_seen < duration
        and timedelta(0) <= now - created < duration
    )


def category_for(repo: dict, projects: dict, config: dict) -> str:
    metadata = projects.get(repo["name"], {})
    if metadata.get("category"):
        return metadata["category"]

    text = " ".join(
        [
            repo.get("name", ""),
            repo.get("description") or "",
            " ".join(repo.get("topics") or []),
        ]
    ).lower()
    for category, keywords in config.get("categories", {}).items():
        if any(keyword.lower() in text for keyword in keywords):
            return category
    return "Other Projects"


def _safe_https_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return value


def _plain_markdown(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("`", "\\`")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _markdown_link(label: str, url: str) -> str:
    safe_url = quote(url, safe=":/?&=#%+;,@~.-_")
    return f"[{label}]({safe_url})"


def _public_project(repo: dict, projects: dict, state: dict, config: dict, now: datetime) -> dict:
    name = repo["name"]
    metadata = projects.get(name, {})
    readme = repo.get("readme")
    languages = sorted(
        language
        for language, size in repo.get("languages", {}).items()
        if isinstance(size, (int, float)) and size > 0
    )
    technologies = list(
        dict.fromkeys(
            [
                *metadata.get("technologies", []),
                *languages,
                *(repo.get("topics") or []),
            ]
        )
    )
    duration = timedelta(days=max(0, config.get("new_badge_days", 14)))
    record = state.get(name, {})
    live_demo = _safe_https_url(metadata.get("live_demo"))
    screenshot = _safe_https_url(metadata.get("screenshot"))

    return {
        "id": f"public:{repo.get('id', name)}",
        "name": name,
        "title": metadata.get("title") or name,
        "description": metadata.get("description")
        or repo.get("description")
        or "Project description not yet added.",
        "category": category_for(repo, projects, config),
        "visibility": "public",
        "repository_url": _safe_https_url(repo.get("html_url")),
        "live_demo": live_demo,
        "screenshot": screenshot,
        "readme_url": _safe_https_url(
            (readme or {}).get("html_url")
        ),
        "featured": bool(metadata.get("featured")),
        "technologies": technologies,
        "language": repo.get("language"),
        "topics": repo.get("topics") or [],
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "created_at": repo.get("created_at"),
        "updated_at": repo.get("updated_at"),
        "is_new": _new_badge(repo, record, now, duration),
        "is_fork": bool(repo.get("fork")),
        "archived": bool(repo.get("archived")),
        "is_empty": repo.get("size") == 0,
        "status": metadata.get("status", ""),
        "related_group": metadata.get("related_group", ""),
    }


def _manual_projects(config: dict) -> list[dict]:
    allowed = {
        "id",
        "title",
        "description",
        "category",
        "visibility",
        "repository_url",
        "technologies",
        "featured",
        "live_demo",
        "screenshot",
        "readme_url",
        "evidence_url",
        "status",
        "related_group",
    }
    results = []
    for item in config.get("manual_projects", []):
        if not isinstance(item, dict) or not item.get("title"):
            raise ValueError("Each manual project must be an object with a title.")

        visibility = item.get("visibility", "private")
        if visibility not in ("private", "public"):
            raise ValueError(
                f"Manual project {item['title']!r} must be public or private."
            )

        project = {
            key: value
            for key, value in item.items()
            if key in allowed
            and key not in {
                "repository_url",
                "live_demo",
                "screenshot",
                "readme_url",
                "evidence_url",
            }
        }
        project["id"] = str(item.get("id") or f"manual:{len(results) + 1}")
        project["description"] = str(item.get("description") or "")
        project["category"] = str(item.get("category") or "Other Projects")
        project["visibility"] = visibility
        project["featured"] = bool(item.get("featured", False))
        project["technologies"] = list(item.get("technologies") or [])
        if visibility == "public":
            project["repository_url"] = _safe_https_url(
                item.get("repository_url")
            )
            for key in ("live_demo", "screenshot", "readme_url", "evidence_url"):
                safe_url = _safe_https_url(item.get(key))
                if safe_url:
                    project[key] = safe_url
            project["repository_url"] = _safe_https_url(
                item.get("repository_url")
            )
        else:
            project["is_new"] = False
            project["is_fork"] = False
            project["archived"] = False
            project["is_empty"] = False
        results.append(project)
    return results


def _language_totals(repos: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for repo in repos:
        for language, size in repo.get("languages", {}).items():
            if isinstance(size, int) and size > 0:
                totals[language] = totals.get(language, 0) + size
    return dict(sorted(totals.items(), key=lambda item: (-item[1], item[0].casefold())))


def build_portfolio_data(
    config: dict,
    repos: list[dict],
    projects: dict,
    state: dict,
    profile_data: dict,
    now: datetime,
) -> dict:
    public_projects = [
        _public_project(repo, projects, state, config, now) for repo in repos
    ]
    all_projects = public_projects + _manual_projects(config)
    all_projects.sort(key=lambda project: (not project["featured"], project["title"].casefold()))
    stars = sum(repo.get("stargazers_count", 0) for repo in repos)
    languages = _language_totals(repos)
    profile = config.get("profile", {})
    safe_links = {
        label: _safe_https_url(url)
        for label, url in profile.get("links", {}).items()
        if _safe_https_url(url)
    }
    email = str(profile.get("email") or "").strip()

    return {
        "profile": {
            "name": profile.get("name", config["username"]),
            "title": profile.get("title", ""),
            "intro": profile.get("intro", ""),
            "about": profile.get("about", ""),
            "portfolio_url": _safe_https_url(profile.get("portfolio_url")),
            "cv_url": _safe_https_url(profile.get("cv_url")),
            "email": email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else "",
            "links": safe_links,
        },
        "skills": config.get("skills", {}),
        "technology_stack": list(
            dict.fromkeys(
                [
                    *config.get("technology_stack", []),
                    *languages.keys(),
                ]
            )
        ),
        "category_order": config.get("category_order", []),
        "achievements": config.get("achievements", []),
        "projects": all_projects,
        "stats": {
            "public_repositories": len(repos),
            "followers": profile_data.get("followers", 0),
            "following": profile_data.get("following", 0),
            "public_stars": stars,
            "public_forks": sum(repo.get("forks_count", 0) for repo in repos),
            "languages": languages,
        },
        "generated_on": now.date().isoformat(),
    }


def featured_rows(data: dict) -> str:
    output = ["| Project | Area | What it demonstrates |", "|---|---|---|"]
    for project in data["projects"]:
        if not project.get("featured"):
            continue
        title = _plain_markdown(project.get("title", "Project"))
        url = project.get("repository_url")
        if url:
            title = _markdown_link(title, url)
        elif project.get("visibility") == "private":
            title = f"{title} (Private Project)"
        output.append(
            f"| {title} | {_plain_markdown(project.get('category', 'Other Projects'))} "
            f"| {_plain_markdown(project.get('description', ''))} |"
        )
    return "\n".join(output)


def repository_rows(data: dict) -> str:
    categories: dict[str, list[str]] = {}
    for project in data["projects"]:
        if project.get("visibility") != "public":
            continue
        title = _plain_markdown(project["title"])
        if project.get("repository_url"):
            title = _markdown_link(title, project["repository_url"])
        if project.get("is_new"):
            title += " · **NEW**"
        if project.get("is_fork"):
            title += " · Fork"
        if project.get("archived"):
            title += " · Archived"
        description = _plain_markdown(project.get("description", ""))
        row = f"| {title} | {description} |"
        categories.setdefault(project.get("category", "Other Projects"), []).append(row)

    category_order = data.get("category_order", [])
    category_names = list(category_order)
    category_names.extend(
        sorted(
            (name for name in categories if name not in category_order),
            key=str.casefold,
        )
    )
    icons = {
        "Network Engineering": "🌐",
        "Cybersecurity & Security Operations": "🛡️",
        "AI & Machine Learning": "🧠",
        "Web Development": "🌱",
        "Software Development": "⚙️",
        "Other Projects": "📁",
    }
    output = []
    for category in category_names:
        if category not in categories:
            continue
        output.extend(
            [
                f"### {icons.get(category, '📌')} {_plain_markdown(category)}",
                "",
                "| Project | What it covers |",
                "|---|---|",
                *categories[category],
                "",
            ]
        )
    return "\n".join(output).strip()


def stats_rows(data: dict) -> str:
    stats = data["stats"]
    output = [
        "| Public repositories | Followers | Following | Stars across public repositories |",
        "|:---:|:---:|:---:|:---:|",
        f"| **{stats['public_repositories']}** | **{stats['followers']}** | "
        f"**{stats['following']}** | **{stats['public_stars']}** |",
        "",
        "**Languages detected across public repositories:** "
        + " · ".join(
            f"`{_plain_markdown(language)}`"
            for language in list(stats["languages"])[:10]
        ),
        "",
        f"<sub>Public GitHub data · refreshed {data['generated_on']}</sub>",
    ]
    return "\n".join(output)


def stack_rows(data: dict) -> str:
    return " · ".join(
        f"`{_plain_markdown(technology)}`"
        for technology in data.get("technology_stack", [])
    )


def skills_rows(data: dict) -> str:
    output = ["| Area | Skills & tools |", "|---|---|"]
    for category, skills in data.get("skills", {}).items():
        items = " · ".join(f"`{_plain_markdown(skill)}`" for skill in skills)
        output.append(f"| **{_plain_markdown(category)}** | {items} |")
    return "\n".join(output)


def _replace_html_marker(content: str, start: str, end: str, value: str) -> str:
    if start not in content or end not in content:
        raise ValueError(f"Missing README markers: {start}, {end}")
    before, remaining = content.split(start, 1)
    _, after = remaining.split(end, 1)
    return f"{before}{start}{value}{end}{after}"


def profile_links(data: dict) -> str:
    links = dict(data["profile"].get("links", {}))
    portfolio_url = data["profile"].get("portfolio_url")
    email = data["profile"].get("email")
    if portfolio_url:
        links["Portfolio"] = portfolio_url
    rendered = []
    badge_colors = {
        "github": "2457A6",
        "linkedin": "176B87",
        "portfolio": "16806B",
        "email": "16806B",
    }
    for label, url in links.items():
        action = "View profile" if label.lower() in {"github", "linkedin"} else "Visit website"
        color = badge_colors.get(label.lower(), "2457A6")
        badge_label = quote(label, safe="")
        badge_action = quote(action, safe="")
        badge = (
            f"https://img.shields.io/badge/{badge_label}-{badge_action}-{color}"
            "?style=for-the-badge"
        )
        rendered.append(
            f'<a href="{escape(url, quote=True)}"><img src="{badge}" '
            f'alt="{escape(label, quote=True)}"></a>'
        )
    if email:
        rendered.append(
            f'<a href="mailto:{escape(email, quote=True)}">'
            '<img src="https://img.shields.io/badge/Email-Contact-16806B?style=for-the-badge" alt="Email"></a>'
        )
    return " &nbsp; ".join(rendered)


def replace_section(content: str, start: str, end: str, replacement: str) -> str:
    if start not in content or end not in content:
        raise ValueError(f"Missing README markers: {start}, {end}")
    before, remaining = content.split(start, 1)
    _, after = remaining.split(end, 1)
    return f"{before}{start}\n{replacement}\n{end}{after}"


def update_readme(data: dict) -> None:
    readme = README.read_text(encoding="utf-8")
    sections = (
        (FEATURE_START, FEATURE_END, featured_rows(data)),
        (START, END, repository_rows(data)),
        (STATS_START, STATS_END, stats_rows(data)),
        (STACK_START, STACK_END, stack_rows(data)),
        (SKILLS_START, SKILLS_END, skills_rows(data)),
        (LINKS_START, LINKS_END, profile_links(data)),
    )
    for start, end, replacement in sections:
        readme = replace_section(readme, start, end, replacement)
    html_sections = (
        (NAME_START, NAME_END, escape(str(data["profile"].get("name", "")))),
        (TITLE_START, TITLE_END, escape(str(data["profile"].get("title", "")))),
        (INTRO_START, INTRO_END, escape(str(data["profile"].get("intro", "")))),
        (ABOUT_START, ABOUT_END, escape(str(data["profile"].get("about", "")))),
    )
    for start, end, replacement in html_sections:
        readme = _replace_html_marker(readme, start, end, replacement)
    save_text(README, readme)


def save_text(path: Path, content: str) -> None:
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")


def validate_config(config: dict, projects: dict) -> None:
    if not re.fullmatch(r"[A-Za-z0-9-]+", config.get("username", "")):
        raise ValueError("config.json must contain a valid GitHub username.")
    if not isinstance(projects, dict):
        raise ValueError("projects.json must contain a JSON object.")
    profile = config.get("profile", {})
    for key in ("portfolio_url", "cv_url"):
        if profile.get(key) and not _safe_https_url(profile[key]):
            raise ValueError(f"profile.{key} must be an HTTPS URL.")
    for label, url in profile.get("links", {}).items():
        if not _safe_https_url(url):
            raise ValueError(f"Profile link {label!r} must be an HTTPS URL.")
    email = str(profile.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("profile.email must be a valid email address.")
    for name, project in projects.items():
        if not isinstance(project, dict):
            raise ValueError(f"Project metadata for {name!r} must be an object.")
        if project.get("live_demo") and not _safe_https_url(project["live_demo"]):
            raise ValueError(f"Project {name!r} has a non-HTTPS live_demo URL.")
        if project.get("screenshot") and not _safe_https_url(project["screenshot"]):
            raise ValueError(f"Project {name!r} has a non-HTTPS screenshot URL.")
    for manual in config.get("manual_projects", []):
        if not isinstance(manual, dict):
            raise ValueError("Each manual project must be a JSON object.")
        if manual.get("visibility", "private") == "public":
            for key in (
                "repository_url",
                "live_demo",
                "screenshot",
                "readme_url",
                "evidence_url",
            ):
                if manual.get(key) and not _safe_https_url(manual[key]):
                    raise ValueError(
                        f"Manual project {manual.get('title', '(untitled)')!r} "
                        f"has a non-HTTPS {key} URL."
                    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the local portfolio data and GitHub profile README."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate local configuration and README markers without calling GitHub.",
    )
    args = parser.parse_args()

    config = load_json(CONFIG)
    projects = load_json(PROJECTS)
    state = load_json(STATE)
    validate_config(config, projects)
    if args.check:
        _manual_projects(config)
        for start, end in (
            (START, END),
            (FEATURE_START, FEATURE_END),
            (STATS_START, STATS_END),
            (STACK_START, STACK_END),
            (SKILLS_START, SKILLS_END),
            (LINKS_START, LINKS_END),
            (NAME_START, NAME_END),
            (TITLE_START, TITLE_END),
            (INTRO_START, INTRO_END),
            (ABOUT_START, ABOUT_END),
        ):
            content = README.read_text(encoding="utf-8")
            if start not in content or end not in content:
                raise ValueError(f"README is missing generation markers: {start}, {end}")
        print("Portfolio configuration and README markers are valid.")
        return

    now = datetime.now(timezone.utc)
    repos = discover(config)
    collect_repository_details(repos)
    profile_data = gh_json(f"users/{config['username']}")
    update_repository_state(repos, state, config, now)
    data = build_portfolio_data(config, repos, projects, state, profile_data, now)

    update_readme(data)
    save_json(DATA, data)
    save_json(STATE, state)
    print(f"Discovered {len(repos)} public repositories.")
    print(f"Generated README and portfolio data at {DATA.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
