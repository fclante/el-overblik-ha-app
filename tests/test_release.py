"""Exercise releases against isolated Git repositories and a synthetic GitHub."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from scripts import release


@pytest.fixture
def repository(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    for name in {*release.VERSION_FILES, "LICENSE", ".gitignore"}:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.ROOT / name, target)
    for name in release.RUNTIME_FILES:
        target = root / release.INTEGRATION / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(release.ROOT / release.INTEGRATION / name, target)
    (root / "README.md").write_text("Synthetic documentation\n")
    # Release checks also run after the real project's version has been bumped.
    release.set_version(root, "0.1.0")
    release.git("init", "-b", "main", cwd=root)
    release.git("config", "user.name", "Test", cwd=root)
    release.git("config", "user.email", "test@example.invalid", cwd=root)
    release.git("add", ".", cwd=root)
    release.git(
        "commit",
        "-m",
        "Synthetic initial source\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
        cwd=root,
    )
    remote = tmp_path / "remote.git"
    release.run("git", "init", "--bare", str(remote), cwd=tmp_path)
    release.git("remote", "add", "origin", str(remote), cwd=root)
    release.git("push", "origin", "main", cwd=root)
    monkeypatch.setattr(release, "ROOT", root)
    return root


@pytest.fixture
def github(repository, tmp_path, monkeypatch):
    server = {"releases": [], "assets": {}, "enabled": True, "runs": []}
    original_run = release.run

    def api(endpoint, *args):
        fields = {}
        method = "GET"
        for index, argument in enumerate(args):
            if argument == "--method":
                method = args[index + 1]
            elif argument in ("-f", "-F"):
                key, value = args[index + 1].split("=", 1)
                fields[key] = json.loads(value) if argument == "-F" else value
        if "private-vulnerability-reporting" in endpoint:
            return {"enabled": server["enabled"]}
        if "/actions/workflows/" in endpoint:
            return [{"workflow_runs": server["runs"]}]
        if "generate-notes" in endpoint:
            return {"body": "Synthetic changes"}
        if "/releases?" in endpoint:
            return [server["releases"]]
        if method == "POST" and endpoint.endswith("/releases"):
            result = {
                **fields,
                "id": len(server["releases"]) + 1,
                "assets": [],
                "prerelease": False,
            }
            server["releases"].append(result)
            return result
        if method == "PATCH":
            result = next(
                r for r in server["releases"] if endpoint.endswith(f"/{r['id']}")
            )
            result.update(fields)
            return result
        raise AssertionError(f"Unexpected synthetic API request: {endpoint}")

    def run(*args, **kwargs):
        if args[0] != "gh":
            return original_run(*args, **kwargs)
        tag = args[3]
        record = next(r for r in server["releases"] if r["tag_name"] == tag)
        if args[2] == "upload":
            path = Path(args[4])
            if (tag, path.name) in server["assets"]:
                raise AssertionError("Attempted to overwrite existing release asset")
            server["assets"][tag, path.name] = path.read_bytes()
            record["assets"].append({"name": path.name})
            return ""
        if args[2] == "download":
            name = args[args.index("--pattern") + 1]
            target = Path(args[args.index("--dir") + 1])
            (target / name).write_bytes(server["assets"][tag, name])
            return ""
        raise AssertionError(f"Unexpected gh command: {args}")

    monkeypatch.setattr(release, "api", api)
    monkeypatch.setattr(release, "run", run)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/integration")
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_SHA", release.git("rev-parse", "HEAD"))
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": "0" * 40}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    return server


@pytest.mark.parametrize(
    ("current", "previous", "explicit", "expected"),
    [
        ("0.1.0", None, False, "0.1.0"),
        ("0.1.0", "0.1.0", False, "0.1.1"),
        ("0.1.0", "0.1.8", False, "0.1.9"),
        ("0.1.9", "0.1.8", True, "0.1.9"),
        ("0.2.0", "0.1.8", True, "0.2.0"),
        ("1.0.0", "0.1.8", True, "1.0.0"),
    ],
)
def test_version_policy(current, previous, explicit, expected):
    assert release.next_version(current, previous, explicit) == expected


@pytest.mark.parametrize("version", ["0.0.9", "0.1.7", "0.1.10", "0.2", "01.2.3"])
def test_invalid_manual_versions_fail(version):
    with pytest.raises(ValueError):
        release.next_version(version, "0.1.8", True)


@pytest.mark.parametrize("version", ["0.1.0", "0.1.1", "1.2.3"])
def test_archive_reproducibility_and_isolated_ha_install(repository, tmp_path, version):
    release.set_version(repository, version)
    first = release.build(repository, tmp_path / "first")
    # Unlisted files must not leak into the archive, even before Git ignores them.
    (repository / release.INTEGRATION / ".env").write_text("synthetic-not-a-token")
    second = release.build(repository, tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()
    assert (first.parent / "SHA256SUMS").read_text() == (
        f"{hashlib.sha256(first.read_bytes()).hexdigest()}  {release.ARCHIVE}\n"
    )
    config = tmp_path / "ha"
    installed = config / release.INTEGRATION
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == release.RUNTIME_FILES
        archive.extractall(installed)
    code = """
import asyncio
import sys
from pathlib import Path
from homeassistant import loader
from homeassistant.core import HomeAssistant
async def main():
    hass = HomeAssistant(str(Path.cwd()))
    loader.async_setup(hass)
    integration = await loader.async_get_integration(hass, "eloverblik_data")
    component = await integration.async_get_component()
    assert Path(component.__file__).resolve().parent == Path.cwd() / "custom_components/eloverblik_data"
    assert integration.version == sys.argv[1]
    await hass.async_stop(force=True)
asyncio.run(main())
"""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"HA_REFRESH_TOKEN", "HA_METER_POINTS"}
    }
    env["PYTHONPATH"] = str(config)
    result = subprocess.run(
        [sys.executable, "-c", code, version],
        cwd=config,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_license_metadata_and_tracked_secret_guards(repository):
    release.set_version(repository, "0.2.0")
    assert release.versions(repository) == "0.2.0"
    (repository / release.INTEGRATION / "LICENSE").write_text("wrong")
    with pytest.raises(ValueError, match="licenses differ"):
        release.check(repository)
    shutil.copyfile(
        repository / "LICENSE", repository / release.INTEGRATION / "LICENSE"
    )
    (repository / ".env").write_text("synthetic")
    release.git("add", "--force", ".env")
    with pytest.raises(ValueError, match="must not be tracked"):
        release.check(repository)


def advance_main(root, tmp_path, filename="README.md", version=None):
    other = tmp_path / "other"
    release.run(
        "git",
        "clone",
        "-b",
        "main",
        str(root.parent / "remote.git"),
        str(other),
        cwd=root.parent,
    )
    release.git("config", "user.name", "Test", cwd=other)
    release.git("config", "user.email", "test@example.invalid", cwd=other)
    path = other / filename
    path.write_text(path.read_text() + "\nLater user change\n")
    if version is not None:
        release.set_version(other, version)
    release.git("add", filename, *release.VERSION_FILES, cwd=other)
    release.git(
        "commit",
        "-m",
        "Synthetic later change\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
        cwd=other,
    )
    release.git("push", "origin", "main", cwd=other)
    return release.git("rev-parse", "HEAD", cwd=other)


def test_docs_push_version_sync_preserves_newer_main(
    repository, github, tmp_path, monkeypatch
):
    state_file = tmp_path / "state.json"
    source = release.git("rev-parse", "HEAD")
    release.prepare(state_file)
    later = advance_main(repository, tmp_path)
    release.publish(state_file, tmp_path / "dist")
    assert release.git("rev-parse", "v0.1.0^{commit}") == source
    assert release.git("rev-parse", "FETCH_HEAD") == later
    assert "Later user change" in release.git("show", "FETCH_HEAD:README.md")
    monkeypatch.setenv("GITHUB_RUN_ID", "101")
    monkeypatch.setenv("GITHUB_SHA", later)
    Path(os.environ["GITHUB_EVENT_PATH"]).write_text(json.dumps({"before": source}))
    release.git("checkout", "--detach", later)
    release.prepare(state_file)
    assert json.loads(state_file.read_text())["version"] == "0.1.1"
    release.publish(state_file, tmp_path / "dist")
    assert release.git("show", "FETCH_HEAD:README.md").endswith("Later user change")
    assert (
        json.loads(release.git("show", f"v0.1.1:{release.VERSION_FILES[0]}"))["version"]
        == "0.1.1"
    )
    release.git("fetch", "origin", "main")
    assert (
        json.loads(release.git("show", f"FETCH_HEAD:{release.VERSION_FILES[0]}"))[
            "version"
        ]
        == "0.1.1"
    )
    assert len(github["releases"]) == 2
    release.git("checkout", "--detach", later)
    release.prepare(state_file)
    release.publish(state_file, tmp_path / "patch-again")
    assert len(github["releases"]) == 2
    # A published rerun is verification, even after a newer version was released.
    monkeypatch.setenv("GITHUB_RUN_ID", "100")
    monkeypatch.setenv("GITHUB_SHA", source)
    release.git("checkout", "--detach", source)
    release.prepare(state_file)
    release.publish(state_file, tmp_path / "first-again")
    assert len(github["releases"]) == 2


def test_partial_draft_resume_without_overwrite(
    repository, github, tmp_path, monkeypatch
):
    state_file = tmp_path / "state.json"
    source = release.git("rev-parse", "HEAD")
    release.prepare(state_file)
    upload = release.upload_assets

    def interrupt(repo, record, output):
        release.run(
            "gh",
            "release",
            "upload",
            record["tag_name"],
            str(output / "SHA256SUMS"),
            "--repo",
            repo,
        )
        raise RuntimeError("Synthetic interruption")

    monkeypatch.setattr(release, "upload_assets", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        release.publish(state_file, tmp_path / "dist")
    assert github["releases"][0]["draft"]
    monkeypatch.setattr(release, "upload_assets", upload)
    release.git("checkout", "--detach", source)
    release.prepare(state_file)
    release.publish(state_file, tmp_path / "dist")
    assert not github["releases"][0]["draft"]
    assert len(github["releases"]) == 1
    assert set(name for _, name in github["assets"]) == release.ASSETS
    # Published bytes cannot be silently replaced on a rerun.
    github["assets"]["v0.1.0", release.ARCHIVE] = b"changed"
    with pytest.raises(ValueError, match="asset differs"):
        release.publish(state_file, tmp_path / "dist")


def test_publication_prerequisites_and_queue_order(repository, github, tmp_path):
    state_file = tmp_path / "state.json"
    github["runs"] = [{"id": 99, "status": "queued"}]
    with pytest.raises(ValueError, match="earlier release run"):
        release.prepare(state_file)
    github["runs"] = []
    release.prepare(state_file)
    github["enabled"] = False
    with pytest.raises(ValueError, match="private vulnerability reporting"):
        release.publish(state_file, tmp_path / "dist")
    assert release.git("ls-remote", "--tags", "origin") == ""
    assert github["releases"] == []


def test_stale_source_never_becomes_newer_release(repository, github, tmp_path):
    source = release.git("rev-parse", "HEAD")
    later = advance_main(repository, tmp_path)
    release.git("fetch", "origin", "main")
    previous = {"source": later, "commit": later, "version": "0.1.0", "run": "99"}
    with pytest.raises(ValueError, match="out of order"):
        release.check_order(
            "example/integration", source, "100", [{"body": release.marker(previous)}]
        )


def test_fast_forward_conflict_retries_without_losing_changes(
    repository, github, tmp_path, monkeypatch
):
    state_file = tmp_path / "state.json"
    release.prepare(state_file)
    original_run = subprocess.run
    attempts = 0

    def race(args, **kwargs):
        nonlocal attempts
        if args[:4] == ["git", "push", "--atomic", "origin"]:
            attempts += 1
            if attempts == 1:
                advance_main(repository, tmp_path)
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", race)
    release.publish(state_file, tmp_path / "dist")
    assert attempts == 2
    release.git("fetch", "origin", "main")
    assert "Later user change" in release.git("show", "FETCH_HEAD:README.md")
    assert not github["releases"][0]["draft"]


def test_snapshot_rejects_nonversion_changes(repository):
    source = release.git("rev-parse", "HEAD")
    (repository / "README.md").write_text("unvalidated")
    release.git("add", "README.md")
    release.git(
        "commit",
        "-m",
        "Synthetic unvalidated change\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
    )
    state = {
        "source": source,
        "commit": release.git("rev-parse", "HEAD"),
        "run": "100",
        "version": "0.1.0",
    }
    with pytest.raises(ValueError, match="unvalidated source changes"):
        release.verify_snapshot(state)


def test_uncommitted_change_after_checks_cannot_be_published(
    repository, github, tmp_path
):
    state_file = tmp_path / "state.json"
    release.prepare(state_file)
    path = repository / release.INTEGRATION / "sensor.py"
    path.write_text(path.read_text() + "\n# Synthetic unvalidated change.\n")
    with pytest.raises(ValueError, match="working tree changed"):
        release.publish(state_file, tmp_path / "dist")
    assert github["releases"] == []
    assert release.git("ls-remote", "--tags", "origin") == ""


def test_tag_only_interruption_resumes_original_version(
    repository, github, tmp_path, monkeypatch
):
    state_file = tmp_path / "state.json"
    release.prepare(state_file)
    original_api = release.api

    def interrupt(endpoint, *args):
        if "generate-notes" in endpoint:
            raise RuntimeError("Synthetic tag-only interruption")
        return original_api(endpoint, *args)

    monkeypatch.setattr(release, "api", interrupt)
    with pytest.raises(RuntimeError, match="tag-only interruption"):
        release.publish(state_file, tmp_path / "dist")
    assert release.git("ls-remote", "--tags", "origin")
    assert github["releases"] == []
    monkeypatch.setattr(release, "api", original_api)
    release.prepare(state_file)
    release.publish(state_file, tmp_path / "dist")
    assert [r["tag_name"] for r in github["releases"]] == ["v0.1.0"]


def test_pending_higher_manual_main_version_is_not_rolled_back(
    repository, github, tmp_path
):
    state_file = tmp_path / "state.json"
    release.prepare(state_file)
    later = advance_main(repository, tmp_path, version="0.2.0")
    release.publish(state_file, tmp_path / "dist")
    release.git("fetch", "origin", "main")
    assert release.git("rev-parse", "FETCH_HEAD") == later
    assert (
        json.loads(release.git("show", f"FETCH_HEAD:{release.VERSION_FILES[0]}"))[
            "version"
        ]
        == "0.2.0"
    )


@pytest.mark.parametrize(
    ("stderr", "expected_attempts", "error"),
    [
        ("non-fast-forward", 3, "three synchronization attempts"),
        ("GH006: protected branch", 1, "bot/ruleset permissions"),
    ],
)
def test_failed_atomic_push_does_not_publish(
    repository, github, tmp_path, monkeypatch, stderr, expected_attempts, error
):
    state_file = tmp_path / "state.json"
    release.prepare(state_file)
    original_run = subprocess.run
    attempts = 0

    def reject(args, **kwargs):
        nonlocal attempts
        if args[:4] == ["git", "push", "--atomic", "origin"]:
            attempts += 1
            return subprocess.CompletedProcess(args, 1, "", stderr)
        return original_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", reject)
    with pytest.raises(RuntimeError, match=error):
        release.publish(state_file, tmp_path / "dist")
    assert attempts == expected_attempts
    assert github["releases"] == []
    assert release.git("ls-remote", "--tags", "origin") == ""


def test_symlinked_brand_directory_is_not_packaged(repository, tmp_path):
    brand = repository / release.INTEGRATION / "brand"
    moved = tmp_path / "artwork"
    brand.rename(moved)
    brand.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinked"):
        release.build(repository, tmp_path / "dist")


def test_workflow_publish_gate_and_token_scope():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load(
        (root / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert workflow["on"] == {"push": {"branches": ["main"]}}
    assert workflow["concurrency"] == {"group": "main-releases", "queue": "max"}
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["release"]
    assert job["needs"] == "validate"
    assert job["permissions"] == {"contents": "write", "actions": "read"}
    steps = job["steps"]
    assert steps[-2]["uses"] == "./.github/actions/check"
    assert " publish " in steps[-1]["run"]
    assert "if" not in steps[-1]  # Failed final checks must skip publication.
    # GITHUB_TOKEN pushes do not dispatch another push workflow.
    assert steps[-1]["env"]["GH_TOKEN"] == "${{ github.token }}"
