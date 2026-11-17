# Contributing

[Læs på dansk](docs/da/CONTRIBUTING.md) · [Project overview](README.md)

Thank you for helping improve ElOverblik Data. This is an independent community integration for Home Assistant, not an official ElOverblik or Home Assistant project. Contributions of code, documentation, translations, and carefully described bug reports are welcome.

## Before opening an issue or pull request

- Search existing issues and pull requests for duplicates.
- Use the GitHub bug report or feature request form. The forms are bilingual.
- Keep reports minimal and scrubbed. **Never include an ElOverblik refresh/access token, full metering-point ID, personal or account data, or an unredacted API response.** Do not attach configuration exports, `.env` files, screenshots containing account details, or raw logs. Describe the affected behavior and provide a synthetic example instead.
- **Do not report security vulnerabilities in public issues or pull requests.** See [SECURITY.md](SECURITY.md); private vulnerability reporting is currently unavailable and must be enabled before release.

## Development setup

Requirements: Python 3.14.2 or newer and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run pytest -q
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy custom_components scripts
uv run python scripts/release.py check
```

For an archive dry run, run checks first, then build to a fresh temporary output directory:

```sh
uv run python scripts/release.py build --output "$(mktemp -d)/eloverblik-dist"
```

The dry run validates versions and the archive locally; it does not commit changes or access the network. Avoid reusing a fixed output directory that might contain a previous build.

Tests use isolated Home Assistant storage and synthetic API responses. They do not need real credentials, real metering points, or live API access. Never put secrets in tests, fixtures, logs, screenshots, issue reports, or pull requests.

## Pull requests

1. Make a focused change and explain the user-visible reason for it.
2. Add or update tests for behavior changed by the contribution; use synthetic and privacy-safe data.
3. Run the relevant checks above and report accurately which commands passed. Do not claim that a live API, Marketplace, GitHub settings, or remote workflow was verified unless it actually was.
4. Update English documentation and its Danish counterpart when behavior, setup, or limitations change.
5. Submit a pull request using the bilingual template. State known limitations and any migration considerations.

There is no Contributor License Agreement (CLA) or Developer Certificate of Origin (DCO). By submitting a contribution, you confirm that you have the right to submit it and agree that it may be distributed under this project's MIT license.

## Release versioning

Releases are intended to be automated from successful pushes to `main`, including documentation-only changes. See [RELEASING.md](docs/RELEASING.md) for version rules, safeguards, administrator prerequisites, and recovery procedures. Do not run the workflow's internal `prepare` or `publish` commands manually.
