"""Checked, reproducible packaging and main-only release transactions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import Any

DOMAIN = "eloverblik_data"
INTEGRATION = Path("custom_components") / DOMAIN
VERSION_FILES = (
    str(INTEGRATION / "manifest.json"),
    "pyproject.toml",
    "uv.lock",
)
RUNTIME_FILES = {
    "__init__.py",
    "api.py",
    "binary_sensor.py",
    "button.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "diagnostics.py",
    "entity.py",
    "models.py",
    "sensor.py",
    "statistics.py",
    "manifest.json",
    "services.yaml",
    "strings.json",
    "LICENSE",
    "translations/en.json",
    "translations/da.json",
    "brand/icon.svg",
    "brand/icon.png",
    "brand/icon@2x.png",
}
ARCHIVE = f"{DOMAIN}.zip"
ASSETS = {ARCHIVE, "SHA256SUMS"}
MARKER = re.compile(r"<!-- eloverblik-release (\{[^\n]+\}) -->")
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
ROOT = Path(__file__).resolve().parents[1]


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    """Run without a shell and surface command failures."""
    result = subprocess.run(
        args, cwd=cwd or ROOT, env=env, text=True, capture_output=True
    )
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def git(*args: str, cwd: Path | None = None) -> str:
    return run("git", *args, cwd=cwd)


def api(endpoint: str, *args: str) -> Any:
    return json.loads(run("gh", "api", endpoint, *args))


def parts(version: str) -> tuple[int, int, int]:
    if not VERSION.fullmatch(version):
        raise ValueError(f"Expected stable X.Y.Z version, got {version!r}")
    major, minor, patch = (int(value) for value in version.split("."))
    return major, minor, patch


def versions(root: Path) -> str:
    manifest = json.loads((root / VERSION_FILES[0]).read_text())["version"]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    packages = tomllib.loads((root / "uv.lock").read_text())["package"]
    locked = [p["version"] for p in packages if p["name"] == "eloverblik-data"]
    if locked != [project] or manifest != project:
        raise ValueError("Manifest, project and lockfile versions must match")
    parts(project)
    return str(project)


def next_version(current: str, previous: str | None, explicit: bool) -> str:
    incoming = parts(current)
    if previous is None:
        return current
    latest = parts(previous)
    patch = (*latest[:2], latest[2] + 1)
    if explicit:
        if incoming <= latest or (incoming[:2] == latest[:2] and incoming != patch):
            raise ValueError(
                "Explicit version must be the next patch or a higher minor/major"
            )
        return current
    return ".".join(map(str, patch))


def set_version(root: Path, version: str) -> None:
    previous = versions(root)
    parts(version)
    manifest_path = root / VERSION_FILES[0]
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = version
    if previous == version:
        return
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    for filename, pattern in (
        ("pyproject.toml", rf'(?m)^(version = "){re.escape(previous)}(")$'),
        (
            "uv.lock",
            r'(\[\[package\]\]\nname = "eloverblik-data"\nversion = ")[^"]+(")',
        ),
    ):
        path = root / filename
        text, count = re.subn(pattern, rf"\g<1>{version}\2", path.read_text(), count=1)
        if count != 1:
            raise ValueError(f"Cannot locate unique project version in {filename}")
        path.write_text(text)
    versions(root)


def check(root: Path | None = None) -> None:
    root = root or ROOT
    versions(root)
    integration = root / INTEGRATION
    if (root / "LICENSE").read_bytes() != (integration / "LICENSE").read_bytes():
        raise ValueError("Root and shipped MIT licenses differ")
    for name in RUNTIME_FILES:
        path = integration / name
        if (
            path.is_symlink()
            or any((integration / parent).is_symlink() for parent in Path(name).parents)
            or not path.resolve().is_relative_to(root.resolve())
            or not path.is_file()
        ):
            raise ValueError(f"Missing or symlinked distribution file: {name}")
    python_files = {p.name for p in integration.glob("*.py")}
    if python_files != {n for n in RUNTIME_FILES if n.endswith(".py")}:
        raise ValueError(
            "Review and update the runtime allowlist for changed Python modules"
        )
    for filename, size in (("icon.png", 256), ("icon@2x.png", 512)):
        header = (integration / "brand" / filename).read_bytes()[:24]
        if (
            header[:8] != b"\x89PNG\r\n\x1a\n"
            or int.from_bytes(header[16:20]) != size
            or int.from_bytes(header[20:24]) != size
        ):
            raise ValueError(f"Invalid brand PNG dimensions: {filename}")
    tracked = git("ls-files", "-z", cwd=root).split("\0")
    for name in filter(None, tracked):
        path = Path(name)
        if (
            any(
                p.startswith(".env") or p in {".storage", ".venv", "customer_responses"}
                for p in path.parts
            )
            or path.name in {"secrets.yaml", "id_rsa"}
            or path.suffix in {".pem", ".key"}
        ):
            raise ValueError(f"Private/development file must not be tracked: {name}")


def build(root: Path, output: Path) -> Path:
    check(root)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ARCHIVE
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as bundle:
        for name in sorted(RUNTIME_FILES):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            bundle.writestr(
                entry,
                (root / INTEGRATION / name).read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    with zipfile.ZipFile(archive) as bundle:
        if set(bundle.namelist()) != RUNTIME_FILES or bundle.testzip() is not None:
            raise ValueError("Archive failed allowlist/integrity verification")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {ARCHIVE}\n")
    return archive


def context() -> tuple[str, str, str]:
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "push"
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ValueError(
            "Publishing requires a trusted push to main; use check/build locally"
        )
    repo = os.environ["GITHUB_REPOSITORY"]
    source = os.environ["GITHUB_SHA"]
    run_id = os.environ["GITHUB_RUN_ID"]
    if (
        not re.fullmatch(r"[\w.-]+/[\w.-]+", repo)
        or not re.fullmatch(r"[a-f0-9]{40}", source)
        or not run_id.isdigit()
    ):
        raise ValueError("Invalid GitHub release context")
    return repo, source, run_id


def provenance(body: str) -> dict[str, str]:
    match = MARKER.search(body)
    if match is None:
        raise ValueError(
            "Release/tag lacks managed source provenance; resolve manually"
        )
    value = json.loads(match[1])
    if (
        not isinstance(value, dict)
        or set(value) != {"source", "run", "version", "commit"}
        or not all(isinstance(v, str) for v in value.values())
    ):
        raise ValueError("Invalid release provenance")
    parts(value["version"])
    if (
        not all(re.fullmatch(r"[a-f0-9]{40}", value[k]) for k in ("source", "commit"))
        or not value["run"].isdigit()
    ):
        raise ValueError("Invalid release source/run")
    return value


def marker(state: dict[str, str]) -> str:
    return "<!-- eloverblik-release " + json.dumps(state, sort_keys=True) + " -->"


def releases(repo: str) -> list[dict[str, Any]]:
    pages = api(f"repos/{repo}/releases?per_page=100", "--paginate", "--slurp")
    result = [release for page in pages for release in page]
    for release in result:
        state = provenance(release["body"] or "")
        if release["tag_name"] != f"v{state['version']}":
            raise ValueError("Release tag and provenance version disagree")
    return result


def ancestor(older: str, newer: str, root: Path | None = None) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=root or ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return result.returncode == 0


def check_order(
    repo: str, source: str, run_id: str, published: list[dict[str, Any]]
) -> None:
    for release in published:
        previous = provenance(release["body"] or "")
        if previous["source"] == source or not ancestor(previous["source"], source):
            raise ValueError(
                "Source already released or out of order; rerun in source order, never retag"
            )
    pages = api(
        f"repos/{repo}/actions/workflows/release.yml/runs?event=push&branch=main&per_page=100",
        "--paginate",
        "--slurp",
    )
    for page in pages:
        for workflow in page["workflow_runs"]:
            if workflow["id"] < int(run_id) and workflow["status"] != "completed":
                raise ValueError(
                    "An earlier release run is still queued/running; rerun after it completes"
                )


def commit_version(root: Path, version: str, source: str, run_id: str) -> str:
    git("add", "--", *VERSION_FILES, cwd=root)
    if git("diff", "--cached", "--name-only", cwd=root):
        timestamp = git("show", "-s", "--format=%cI", source, cwd=root)
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        }
        run(
            "git",
            "commit",
            "-m",
            f"Release v{version} [release metadata]\n\nSource: {source}\nRun: {run_id}\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>",
            cwd=root,
            env=env,
        )
    return git("rev-parse", "HEAD", cwd=root)


def verify_snapshot(state: dict[str, str], root: Path | None = None) -> None:
    root = root or ROOT
    if git("rev-parse", "HEAD", cwd=root) != state["commit"]:
        raise ValueError("Release checkout changed after preparation")
    if git("status", "--porcelain", "--untracked-files=no", cwd=root):
        raise ValueError("Release working tree changed after preparation")
    if versions(root) != state["version"]:
        raise ValueError("Release snapshot version changed")
    changed = set(
        filter(
            None,
            git(
                "diff", "--name-only", state["source"], state["commit"], cwd=root
            ).splitlines(),
        )
    )
    if not changed <= set(VERSION_FILES):
        raise ValueError("Release snapshot contains unvalidated source changes")
    if not ancestor(state["source"], state["commit"], root):
        raise ValueError("Release snapshot is not based on its source")


def prepare(state_path: Path) -> None:
    repo, source, run_id = context()
    if git("rev-parse", "HEAD") != source or git(
        "status", "--porcelain", "--untracked-files=no"
    ):
        raise ValueError("Preparation requires a clean checkout of the exact push SHA")
    check()
    git("fetch", "origin", "main", "--tags")
    all_releases = releases(repo)
    owned = [r for r in all_releases if provenance(r["body"] or "")["run"] == run_id]
    for tag in git("tag", "--list", "v*").splitlines():
        if not any(r["tag_name"] == tag for r in all_releases):
            pending = provenance(
                git("for-each-ref", "--format=%(contents)", f"refs/tags/{tag}")
            )
            if pending["run"] != run_id:
                raise ValueError(
                    f"Unfinished tagged release {tag}; rerun its original workflow first"
                )
    if owned:
        if len(owned) != 1:
            raise ValueError("Multiple releases claim this run")
        state = provenance(owned[0]["body"] or "")
        if state["source"] != source:
            raise ValueError("Existing release belongs to a different source")
        if owned[0]["draft"]:
            check_order(
                repo,
                source,
                run_id,
                [r for r in all_releases if not r["draft"] and not r["prerelease"]],
            )
        git("checkout", "--detach", f"refs/tags/{owned[0]['tag_name']}^{{commit}}")
        if git("rev-parse", "HEAD") != state["commit"]:
            raise ValueError("Existing release tag moved")
    else:
        if any(r["draft"] for r in all_releases):
            raise ValueError("An earlier draft release is unfinished; rerun it first")
        published = [r for r in all_releases if not r["draft"] and not r["prerelease"]]
        check_order(repo, source, run_id, published)
        latest = max(
            (provenance(r["body"] or "")["version"] for r in published),
            key=parts,
            default=None,
        )
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        before = event["before"]
        explicit = False
        if before != "0" * 40:
            prior = json.loads(git("show", f"{before}:{VERSION_FILES[0]}"))["version"]
            explicit = prior != versions(ROOT)
        version = next_version(versions(ROOT), latest, explicit)
        set_version(ROOT, version)
        commit = commit_version(ROOT, version, source, run_id)
        state = {"source": source, "run": run_id, "version": version, "commit": commit}
    verify_snapshot(state)
    state_path.write_text(json.dumps(state) + "\n")
    print(f"Prepared v{state['version']} from {source}; nothing published")


def push_snapshot(state: dict[str, str], root: Path | None = None) -> None:
    """Atomically tag the snapshot and fast-forward only main's version metadata."""
    root = root or ROOT
    tag = f"v{state['version']}"
    existing = git("tag", "--list", tag, cwd=root)
    if existing:
        if git("rev-parse", f"{tag}^{{commit}}", cwd=root) != state["commit"]:
            raise ValueError(
                "Existing tag targets different code; refusing to overwrite"
            )
        if (
            provenance(
                git(
                    "for-each-ref", "--format=%(contents)", f"refs/tags/{tag}", cwd=root
                )
            )
            != state
        ):
            raise ValueError("Existing tag provenance differs")
    else:
        git(
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "tag",
            "-a",
            tag,
            state["commit"],
            "-m",
            marker(state),
            cwd=root,
        )
    for _ in range(3):
        git("fetch", "origin", "main", cwd=root)
        head = git("rev-parse", "FETCH_HEAD", cwd=root)
        if not ancestor(state["source"], head, root):
            raise ValueError("Main no longer descends from the validated source")
        refs = [f"refs/tags/{tag}:refs/tags/{tag}"]
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary) / "main"
            git("worktree", "add", "--detach", str(tree), head, cwd=root)
            try:
                current = versions(tree)
                if parts(current) > parts(state["version"]):
                    print(f"Preserving pending higher main version {current}")
                elif head == state["source"]:
                    refs.append(f"{state['commit']}:refs/heads/main")
                elif current != state["version"]:
                    set_version(tree, state["version"])
                    commit = commit_version(
                        tree, state["version"], state["source"], state["run"]
                    )
                    refs.append(f"{commit}:refs/heads/main")
                result = subprocess.run(
                    ["git", "push", "--atomic", "origin", *refs],
                    cwd=root,
                    text=True,
                    capture_output=True,
                )
            finally:
                git("worktree", "remove", str(tree), cwd=root)
        if result.returncode == 0:
            return
        if (
            "fetch first" not in result.stderr
            and "non-fast-forward" not in result.stderr
        ):
            raise RuntimeError(
                f"Tag/main push failed; check bot/ruleset permissions: {result.stderr}"
            )
    raise RuntimeError(
        "Main advanced during three synchronization attempts; rerun this workflow"
    )


def upload_assets(repo: str, release: dict[str, Any], output: Path) -> None:
    existing = {asset["name"] for asset in release["assets"]}
    if existing - ASSETS:
        raise ValueError("Unexpected release assets; refusing to modify the release")
    if not release["draft"] and existing != ASSETS:
        raise ValueError(
            "Published release assets are incomplete; manual recovery required"
        )
    for filename in sorted(ASSETS):
        if filename in existing:
            with tempfile.TemporaryDirectory() as temporary:
                run(
                    "gh",
                    "release",
                    "download",
                    release["tag_name"],
                    "--repo",
                    repo,
                    "--pattern",
                    filename,
                    "--dir",
                    temporary,
                )
                if (Path(temporary) / filename).read_bytes() != (
                    output / filename
                ).read_bytes():
                    raise ValueError(
                        f"Existing release asset differs: {filename}; never overwrite"
                    )
        else:
            run(
                "gh",
                "release",
                "upload",
                release["tag_name"],
                str(output / filename),
                "--repo",
                repo,
            )


def publish(state_path: Path, output: Path) -> None:
    repo, source, run_id = context()
    state = provenance(marker(json.loads(state_path.read_text())))
    if state["source"] != source or state["run"] != run_id:
        raise ValueError("Release state belongs to another run/source")
    verify_snapshot(state)
    build(ROOT, output)
    all_releases = releases(repo)
    matches = [r for r in all_releases if r["tag_name"] == f"v{state['version']}"]
    release = matches[0] if matches else None
    if release is not None and provenance(release["body"] or "") != state:
        raise ValueError("Version already belongs to another release")
    if not release or release["draft"]:
        if not api(f"repos/{repo}/private-vulnerability-reporting")["enabled"]:
            raise ValueError(
                "Enable private vulnerability reporting before the first publication"
            )
        push_snapshot(state)
    if release is None:
        previous = [r for r in all_releases if not r["draft"] and not r["prerelease"]]
        args = ["--method", "POST", "-f", f"tag_name=v{state['version']}"]
        if previous:
            latest = max(
                previous, key=lambda r: parts(provenance(r["body"] or "")["version"])
            )
            args += ["-f", f"previous_tag_name={latest['tag_name']}"]
        generated = api(f"repos/{repo}/releases/generate-notes", *args)["body"]
        notes = (
            f"## Release / Udgivelse v{state['version']}\n\n"
            "Install the ZIP through Home Assistant Marketplace. / Installer ZIP via Home Assistant Marketplace.\n\n"
            "Delayed electricity data; no full-bill prices. / Forsinkede eldata; ingen samlet elpris.\n\n"
            f"[Setup and limitations](https://github.com/{repo}/blob/v{state['version']}/README.md) / "
            f"[Opsaetning og begraensninger](https://github.com/{repo}/blob/v{state['version']}/docs/da/README.md).\n\n"
            f"{generated}\n\n{marker(state)}"
        )
        release = api(
            f"repos/{repo}/releases",
            "--method",
            "POST",
            "-f",
            f"tag_name=v{state['version']}",
            "-f",
            f"name=v{state['version']}",
            "-f",
            f"body={notes}",
            "-F",
            "draft=true",
        )
    upload_assets(repo, release, output)
    if release["draft"]:
        api(
            f"repos/{repo}/releases/{release['id']}",
            "--method",
            "PATCH",
            "-F",
            "draft=false",
            "-f",
            "make_latest=true",
        )
    print(f"Verified published release v{state['version']} from {source}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "build", "prepare", "publish"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--state", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "check":
            check()
        elif args.command == "build":
            if args.output is None:
                parser.error("build requires --output")
            print(build(ROOT, args.output))
        else:
            if args.state is None:
                parser.error("prepare/publish require --state")
            if args.command == "prepare":
                prepare(args.state)
            else:
                if args.output is None:
                    parser.error("publish requires --output")
                publish(args.state, args.output)
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f"Release error: {error}\n")


if __name__ == "__main__":
    main()
