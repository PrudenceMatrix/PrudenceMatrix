# Profile README generator

The repository root `README.md` is designed to be the GitHub profile page. The generator refreshes its project catalog and public statistics from the GitHub API; it does not create repositories or push changes.

## Requirements

- Python 3.10+
- GitHub CLI (`gh`), authenticated for local generation

## Edit profile content

- `config.json`: title, biography, skills, technology stack, links, category ordering, and portfolio options.
- `projects.json`: curated project names, descriptions, categories, and featured choices.

Only add contact details and links approved for public display. Public repositories are discovered from GitHub; private repositories are not included.

## Generate and verify

```bash
python3 -m unittest discover -s tests -v
python3 portfolio/generate.py --check
python3 portfolio/generate.py
```

Generation updates the root README, `data.json`, and discovery state. Review the diff before manually pushing changes. The workflow in `.github/workflows/update-portfolio.yml` can also refresh the README on its schedule or via manual dispatch.
