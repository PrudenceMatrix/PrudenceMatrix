# Profile README generator

The repository root `README.md` is designed to be the GitHub profile page. The generator refreshes its project catalog and public statistics from the GitHub API; it does not create repositories or push changes.

## Requirements

- Python 3.10+
- GitHub CLI (`gh`), authenticated for local generation

## Edit profile content

- `config.json`: title, biography, priority-ordered skills, technology stack, links, category ordering, and portfolio options.
- `projects.json`: curated project names, descriptions, categories, and featured choices.

Only add contact details and links approved for public display. Public repositories are discovered from GitHub; private repositories are not included.

The root profile README is the GitHub-facing presentation. Its marked sections are regenerated, so keep every marker pair intact when changing the layout. The blue profile banner is maintained in `assets/profile-banner.svg`.

## Generate and verify

```bash
python3 -m unittest discover -s tests -v
python3 portfolio/generate.py --check
python3 portfolio/generate.py
```

Generation updates the root README, `data.json`, and discovery state. Review the diff before manually pushing changes. The workflow in `.github/workflows/update-portfolio.yml` can also refresh the README on its schedule or via manual dispatch.
