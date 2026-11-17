# Release process

[Læs på dansk](da/RELEASING.md) · [Project overview](../README.md)

Every push to `main`, including documentation-only changes, queues the whole release workflow (`queue: max 100`); pushes are not silently coalesced. Failed validation blocks publication. The automation builds from and verifies the exact source commit selected for that release. A local dry run cannot verify GitHub settings, workflow behavior, or live Marketplace availability.

## Versioning

- The first release is **`v0.1.0`**.
- After that, each successful `main` push produces the next patch version automatically.
- For a planned minor or major release, update the version consistently in `custom_components/eloverblik_data/manifest.json`, `pyproject.toml`, and `uv.lock` in the same source change. The release automation must validate that these versions agree before publishing.
- The release bot's follow-up commit changes version metadata only. GitHub token recursion suppression prevents that bot commit from starting another release.

The release publisher checks GitHub's private vulnerability reporting setting with a GitHub API `GET` request and blocks unless reporting is enabled. This check occurs before it creates a tag or pushes any remote metadata. The main release job needs `actions: read` to inspect workflow runs and `contents: write` for release publication and its narrowly scoped version update; validation jobs do not need write access.

Final validation and archive construction must use the exact versioned source snapshot selected for that release. A version bump must not be validated at one commit and then published from a different branch tip.

Release tests use an isolated synthetic repository with a fixed initial version, independent of the source snapshot's version. Archive installation checks cover the initial version and later patch and major versions.

## Validation and release transaction

The default release validation runs, in order:

```sh
uv sync --locked
uv run pytest -q
uv run ruff check custom_components tests scripts
uv run ruff format --check custom_components tests scripts
uv run mypy custom_components scripts
uv run python scripts/release.py check
```

It also runs the official Home Assistant hassfest validator from a digest-pinned image. The image digest is embedded in a composite action's shell `run` command, so maintainers must review and update it manually; Dependabot does not discover image references embedded in shell commands. A separate, independent, read-only job runs the official HACS validator from a digest-pinned image; there is no brand-based exemption. Offline manifest-schema and local brand checks do not replace the live HACS checks of the public repository, its metadata and the candidate commit. The release job has the required `actions: read` permission. GitHub Actions permissions and remote settings must remain least-privilege.

The latest installed actionlint is 1.7.12, which does not recognize GitHub's documented `queue: max` key. The exact queue configuration is covered by tests; when actionlint is used, only that unsupported-key diagnostic is excluded. There is no actionlint CI job.

Keep the Python and `uv` pins/lock in step with the target Home Assistant Core version, currently 2026.11.2. Review and update Core, Python, `uv`, action references, and validator image digests together, then run the default validation. Dependabot covers Actions/`uv` and action references, but not image references written inside shell `run` commands.

The source SHA, commit, workflow run, and version are recorded in the annotated tag and GitHub Release body. Before publication, release metadata and assets are checked against this provenance. A partial tag/draft transaction blocks later runs until the original run is rerun and recovered. A rerun for an already published version verifies its immutable assets and does not bump the version again.

All queued runs are considered in order. If an earlier queued run is out of order, the workflow uses the GitHub workflow API to detect it and visibly fails the later run; it must not silently coalesce or skip runs. If a later `main` commit already explicitly sets a higher version, publishing the earlier snapshot preserves that pending higher version and does not roll `main` back. Otherwise, the release performs an atomic tag and version-only `main` update, with up to three compare-and-swap (CAS) attempts. It never force-pushes.

## What a release contains

- `eloverblik_data.zip`: installable integration files at the archive root (the archive must not add an extra enclosing repository directory).
- `SHA256SUMS`: checksum information for the release archive.
- GitHub Release notes: the canonical changelog for that version.

The archive must be built and checked against the exact validated source SHA. Never substitute files from a later branch tip for that source snapshot.

## Contributor dry run

For a local dry run, run the local check before the archive build:

```sh
uv sync --locked
uv run python scripts/release.py check
uv run python scripts/release.py build --output "$(mktemp -d)/eloverblik-dist"
```

`check` validates local release prerequisites. `build` validates versions and produces the archive locally; it does not commit changes or access GitHub/the network. Use a fresh output directory rather than a fixed path that might collide with a prior run. These commands do **not** exercise the full default validation, remote GitHub settings, the private-reporting API guard, or confirm that Marketplace installation works.

The `prepare` and `publish` script commands are workflow internals; **do not run them manually for a local release**. A local archive build is not a published release.

## Validation branches without publication

Push a non-`main` validation branch to run the GitHub checks without creating a tag or release. Successful archive checks upload `validation-zip-<source-SHA>` under the workflow run's artifacts, containing only `eloverblik_data.zip` and `SHA256SUMS`, retained for seven days. Download and verify the checksum before testing the ZIP in an isolated Home Assistant configuration.

This validates the candidate package, not the release publisher or Marketplace's installation of a published release. The HACS check still needs real repository metadata such as a description, topics and a detectable license. An empty repository's first pushed branch may become its default branch; it does not create `main` or publish a release.

## Repository administrator checklist

Before the first release, an administrator must review and apply the following GitHub repository settings:

1. Enable GitHub private vulnerability reporting and verify that the private reporting option is actually available. Do not release while it is disabled. See [SECURITY.md](../SECURITY.md).
2. Enable Dependabot security updates/alerts as appropriate.
3. Set a clear repository description and relevant topics, without implying endorsement by ElOverblik or Home Assistant. After the license files reach the default branch, confirm GitHub detects the intended MIT license. These remote metadata checks have not been verified locally.
4. Ensure `main` protection permits the narrowly scoped release bot's version-metadata-only commit using the built-in GitHub token. If branch protection cannot permit that narrowly scoped change, **stop and resolve the policy before release**. Do not use a personal access token or broad protection bypass.
5. Grant `contents: write` only to the release job that needs to create release metadata and its version-only `main` update. Grant that job `actions: read` only as needed to inspect workflow runs. Validation jobs should not receive write permission.

These are remote settings and have not been verified by the local checks. The first successful push to `main` triggers the initial `v0.1.0` release; no push is authorized or implied by this documentation.

## Failure and recovery

- Failed validation must not publish a release.
- A partial tag/draft transaction blocks later runs. Retry or recover it by rerunning the same original workflow run and source SHA; do not start a replacement release from a different branch tip.
- If an already published version is rerun, it must verify the existing immutable assets and must not bump or republish that version.
- Do not delete, move, or retag an already published release to repair ordering.
- If workflow-API inspection detects an earlier queued run out of order, the later run must fail visibly rather than silently skipping or coalescing it. Recover releases in order from their original validated source commits.
- Preserve a higher version explicitly pending on `main` when releasing an earlier snapshot. If no higher version is pending, the version-only update must use the atomic CAS mechanism (up to three attempts). Never force-push.
- Check the workflow run, source SHA, archive contents, checksum, and release notes before asking an administrator to intervene. Do not retry with broader credentials or permissions.
