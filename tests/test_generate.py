import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from subprocess import CompletedProcess

from portfolio.generate import (
    _manual_projects,
    _new_badge,
    build_portfolio_data,
    category_for,
    discover,
    repository_rows,
    skills_rows,
    update_repository_state,
    validate_config,
)


NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


class PortfolioGeneratorTests(unittest.TestCase):
    def test_discovery_uses_pagination_and_keeps_all_public_repository_kinds(self):
        repositories = [
            {
                "id": 1,
                "name": "regular",
                "private": False,
                "visibility": "public",
                "fork": False,
                "archived": False,
            },
            {
                "id": 2,
                "name": "forked",
                "private": False,
                "visibility": "public",
                "fork": True,
                "archived": False,
            },
            {
                "id": 3,
                "name": "archived",
                "private": False,
                "visibility": "public",
                "fork": False,
                "archived": True,
            },
            {
                "id": 4,
                "name": "private",
                "private": True,
                "visibility": "private",
            },
        ]
        result = CompletedProcess(
            args=[],
            returncode=0,
            stdout="\n".join(json.dumps(item) for item in repositories),
            stderr="",
        )
        with patch("portfolio.generate.subprocess.run", return_value=result) as run:
            found = discover({"username": "PrudenceMatrix"})

        self.assertIn("--paginate", run.call_args.args[0])
        self.assertEqual({repo["name"] for repo in found}, {"regular", "forked", "archived"})

    def test_new_badge_requires_recent_creation_and_first_discovery(self):
        recent = {
            "created_at": (NOW - timedelta(days=2)).isoformat(),
        }
        state = {}
        config = {"new_badge_days": 14}
        update_repository_state(
            [{"id": 1, "name": "recent", **recent}],
            state,
            config,
            NOW,
        )
        self.assertTrue(_new_badge(recent, state["recent"], NOW, timedelta(days=14)))

        old_updated_repository = {
            "created_at": (NOW - timedelta(days=90)).isoformat(),
            "updated_at": NOW.isoformat(),
        }
        old_state = {}
        update_repository_state(
            [{"id": 2, "name": "old", **old_updated_repository}],
            old_state,
            config,
            NOW,
        )
        self.assertFalse(
            _new_badge(
                old_updated_repository,
                old_state["old"],
                NOW,
                timedelta(days=14),
            )
        )

    def test_renamed_repository_keeps_its_existing_discovery_state(self):
        seen = (NOW - timedelta(days=3)).isoformat()
        state = {"old-name": {"repository_id": 25, "first_seen": seen, "baseline": False}}
        repo = {
            "id": 25,
            "name": "new-name",
            "created_at": (NOW - timedelta(days=3)).isoformat(),
        }

        update_repository_state([repo], state, {"new_badge_days": 14}, NOW)

        self.assertNotIn("old-name", state)
        self.assertEqual(state["new-name"]["first_seen"], seen)
        self.assertTrue(
            _new_badge(repo, state["new-name"], NOW, timedelta(days=14))
        )

    def test_category_uses_repository_topics(self):
        repo = {"name": "project-x", "description": None, "topics": ["network-security"]}
        config = {"categories": {"Network Engineering": ["network"]}}
        self.assertEqual(category_for(repo, {}, config), "Network Engineering")

    def test_manual_private_projects_never_export_repository_or_external_urls(self):
        config = {
            "manual_projects": [
                {
                    "id": "safe-title",
                    "title": "Private lab",
                    "description": "Approved public summary",
                    "visibility": "private",
                    "repository_url": "https://github.com/private/repository",
                    "readme_url": "https://github.com/private/repository/README.md",
                }
            ]
        }

        project = _manual_projects(config)[0]

        self.assertEqual(project["visibility"], "private")
        self.assertNotIn("repository_url", project)
        self.assertNotIn("readme_url", project)

    def test_stats_are_aggregated_from_api_data_and_manual_private_data_is_included(self):
        config = {
            "username": "PrudenceMatrix",
            "profile": {"links": {}, "email": ""},
            "skills": {},
            "technology_stack": [],
            "manual_projects": [
                {
                    "title": "Private lab",
                    "description": "Approved summary",
                    "visibility": "private",
                }
            ],
        }
        repos = [
            {
                "id": 1,
                "name": "repo",
                "html_url": "https://github.com/PrudenceMatrix/repo",
                "language": "Python",
                "languages": {"Python": 120, "HTML": 20},
                "topics": [],
                "stargazers_count": 3,
                "forks_count": 2,
                "created_at": NOW.isoformat(),
                "updated_at": NOW.isoformat(),
                "size": 1,
            }
        ]
        state = {"repo": {"first_seen": NOW.isoformat(), "baseline": True}}

        data = build_portfolio_data(
            config, repos, {}, state, {"followers": 4, "following": 5}, NOW
        )

        self.assertEqual(data["stats"]["public_repositories"], 1)
        self.assertEqual(data["stats"]["public_stars"], 3)
        self.assertEqual(data["stats"]["languages"], {"Python": 120, "HTML": 20})
        private = next(project for project in data["projects"] if project["visibility"] == "private")
        self.assertNotIn("repository_url", private)

    def test_configuration_rejects_non_https_links(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_config(
                {
                    "username": "PrudenceMatrix",
                    "profile": {"links": {"Demo": "javascript:alert(1)"}},
                },
                {},
            )

    def test_readme_project_catalog_includes_every_public_project_in_configured_order(self):
        projects = [
            {
                "title": "A network project",
                "description": "Network assessment.",
                "category": "Network Engineering",
                "visibility": "public",
                "repository_url": "https://github.com/example/network",
                "language": None,
                "is_new": True,
            },
            {
                "title": "A security project",
                "description": "Defensive security lab.",
                "category": "Cybersecurity & Security Operations",
                "visibility": "public",
                "repository_url": "https://github.com/example/security",
                "language": "Python",
            },
            {
                "title": "A web project",
                "description": "Website project.",
                "category": "Web Development",
                "visibility": "public",
                "repository_url": "https://github.com/example/web",
                "language": "TypeScript",
            },
            {
                "title": "A private project",
                "description": "Do not show.",
                "category": "Other Projects",
                "visibility": "private",
            },
        ]
        data = {
            "projects": projects,
            "category_order": [
                "Network Engineering",
                "Cybersecurity & Security Operations",
                "Web Development",
            ],
        }

        rendered = repository_rows(data)

        self.assertIn("A network project", rendered)
        self.assertIn("**NEW**", rendered)
        self.assertNotIn("**[A network project]", rendered)
        self.assertIn("A security project", rendered)
        self.assertIn("A web project", rendered)
        self.assertNotIn("A private project", rendered)
        self.assertLess(
            rendered.index("Network Engineering"),
            rendered.index("Cybersecurity & Security Operations"),
        )
        self.assertLess(
            rendered.index("Cybersecurity & Security Operations"),
            rendered.index("Web Development"),
        )

    def test_skills_render_as_grouped_plain_labels_without_proficiency_scores(self):
        rendered = skills_rows(
            {
                "skills": {
                    "Networking": ["TCP/IP", "Network Scanning"],
                    "Web Development": ["HTML", "CSS"],
                }
            }
        )

        self.assertIn("**Networking**", rendered)
        self.assertIn("`TCP/IP`", rendered)
        self.assertIn("**Web Development**", rendered)
        self.assertNotIn("%", rendered)


if __name__ == "__main__":
    unittest.main()
