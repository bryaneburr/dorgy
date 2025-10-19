"""Invoke tasks for packaging, testing, and release automation.

This module provides a lightweight Invoke collection that shells out to the `uv`
CLI so routine project workflows—version bumps, builds, publishes, testing, and
linting—stay consistent with the rest of the toolchain.
"""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from invoke import Collection, Context, task
from invoke.runners import Result

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"


def _run_uv(
    ctx: Context,
    args: Sequence[str],
    *,
    echo: bool = True,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
) -> Result | None:
    """Execute a uv command with consistent quoting, logging, and PTY defaults.

    Args:
        ctx: Invoke execution context.
        args: Additional arguments to append after the `uv` executable.
        echo: Whether to echo the command before running it.
        dry_run: When True, log the command without executing it.
        env: Optional environment variables to layer onto the invocation.
    """
    command = shlex.join(("uv", *args))
    if dry_run:
        print(f"[dry-run] {command}")
        return None
    run_env = dict(ctx.config.run.env or {})
    if env:
        run_env.update(env)
    return ctx.run(command, echo=echo, pty=True, env=run_env)


def _get_current_version(ctx: Context) -> str:
    """Return the project version reported by `uv version --short`."""

    result = ctx.run("uv version --short", hide=True, pty=False)
    return result.stdout.strip()


def _predict_bumped_version(ctx: Context, part: str) -> str:
    """Return the version that would result from bumping the given semantic part."""

    result = ctx.run(
        f"uv version --bump {shlex.quote(part)} --dry-run --short",
        hide=True,
        pty=False,
    )
    return result.stdout.strip()


def _commit_version_files(ctx: Context, files: Sequence[str], message: str) -> bool:
    """Stage the provided files and commit them with the supplied message.

    Args:
        ctx: Invoke execution context.
        files: Iterable of file paths to stage.
        message: Commit message to use when changes are present.

    Returns:
        bool: ``True`` when a commit was created, ``False`` otherwise.
    """

    files_args = " ".join(shlex.quote(file) for file in files)
    status = ctx.run(
        f"git status --porcelain -- {files_args}",
        hide=True,
        pty=False,
    ).stdout.strip()
    if not status:
        print("No version file changes detected; skipping commit.")
        return False
    ctx.run(f"git add {files_args}", echo=True)
    ctx.run(f"git commit -m {shlex.quote(message)}", echo=True)
    return True


@task
def sync(ctx: Context, dev: bool = True) -> None:
    """Synchronize the project's virtual environment with uv.

    Args:
        ctx: Invoke execution context.
        dev: Include development extras (e.g., tests, linting) when True.
    """
    args = ["sync"]
    if dev:
        args.extend(["--extra", "dev"])
    _run_uv(ctx, args)


@task(help={"clean": "Remove existing artifacts from dist/ before building."})
def build(ctx: Context, clean: bool = False) -> None:
    """Build source and wheel distributions in `dist/` using uv.

    Args:
        ctx: Invoke execution context.
        clean: Delete prior artifacts in `dist/` before building.
    """
    if clean and DIST_DIR.exists():
        for artifact in DIST_DIR.iterdir():
            if artifact.is_file():
                artifact.unlink()
            else:
                shutil.rmtree(artifact)
    _run_uv(ctx, ["build"])


@task(
    help={
        "part": "Semantic version component to bump (major, minor, patch).",
        "value": "Explicit version string to set instead of bumping.",
        "dry_run": "Print the resolved version without mutating pyproject.toml.",
    }
)
def bump_version(
    ctx: Context,
    part: str = "patch",
    value: str | None = None,
    dry_run: bool = False,
) -> None:
    """Update the project version via uv's semantic version helpers.

    Args:
        ctx: Invoke execution context.
        part: Named semantic component to bump.
        value: Explicit version to set when provided.
        dry_run: Emit the resulting version without writing changes.
    """
    args: list[str] = ["version"]
    if value:
        args.append(value)
    else:
        args.extend(["--bump", part])
    if dry_run:
        args.append("--dry-run")
    _run_uv(ctx, args)


@task(
    help={
        "index_url": "Override the package index URL (defaults to PyPI).",
        "token": "API token to pass to uv publish (will appear in command output).",
        "skip_existing": "Skip files already present on the target index.",
        "dry_run": "Log the publish command without executing it.",
    }
)
def publish(
    ctx: Context,
    index_url: str | None = None,
    token: str | None = None,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> None:
    """Upload built distributions to the configured package index.

    Args:
        ctx: Invoke execution context.
        index_url: Package index endpoint (use TestPyPI during dry runs).
        token: API token to include with the upload *in clear text*.
        skip_existing: Avoid re-uploading distributions that already exist.
        dry_run: Print the command instead of executing it.
    """
    args: list[str] = ["publish"]
    if index_url:
        args.extend(["--index-url", index_url])
    if skip_existing:
        args.append("--skip-existing")
    if token:
        args.extend(["--token", token])
    _run_uv(ctx, args, dry_run=dry_run, echo=token is None)


@task(
    help={
        "version": "Version string to tag (defaults to the project version).",
        "prefix": "Prefix to prepend to the git tag (defaults to 'v').",
        "message": "Annotated tag message (defaults to 'Release <tag>').",
        "push": "Push the created tag to origin after creation.",
        "force": "Replace an existing tag with the same name.",
        "dry_run": "Print git commands without executing them.",
    }
)
def tag_version(
    ctx: Context,
    version: str | None = None,
    prefix: str = "v",
    message: str | None = None,
    push: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    """Create and optionally push a git tag for the current project version.

    Args:
        ctx: Invoke execution context.
        version: Explicit version identifier to tag.
        prefix: Optional prefix (e.g., ``v``) to prepend to the tag name.
        message: Annotated tag message.
        push: Push the created tag to ``origin`` when True.
        force: Overwrite an existing tag with the same name.
        dry_run: Log git commands without executing them.

    Raises:
        RuntimeError: If the tag already exists and ``force`` is False.
    """

    resolved_version = version or _get_current_version(ctx)
    tag_name = f"{prefix}{resolved_version}" if prefix else resolved_version
    tag_message = message or f"Release {tag_name}"

    if dry_run:
        force_flag = " -f" if force else ""
        cmd_preview = (
            f"git tag{force_flag} -a {shlex.quote(tag_name)} -m {shlex.quote(tag_message)}"
        )
        print(f"[dry-run] {cmd_preview}")
        if push:
            print(f"[dry-run] git push origin {shlex.quote(tag_name)}")
        return

    if not force:
        result = ctx.run(
            f"git rev-parse {shlex.quote(tag_name)}",
            warn=True,
            hide=True,
            pty=False,
        )
        if result.ok:
            raise RuntimeError(f"Tag {tag_name} already exists. Pass force=True to replace it.")

    tag_parts = ["git", "tag"]
    if force:
        tag_parts.append("-f")
    tag_parts.extend(["-a", tag_name, "-m", tag_message])
    ctx.run(" ".join(shlex.quote(part) for part in tag_parts), echo=True)

    if push:
        ctx.run(f"git push origin {shlex.quote(tag_name)}", echo=True)


@task(
    help={
        "part": "Semantic version component to bump before publishing.",
        "index_url": "Package index endpoint for the publish step.",
        "token": "API token passed to uv publish (printed if provided).",
        "skip_existing": "Skip artifacts already present on the target index.",
        "dry_run": "Log the composed workflow without executing it.",
        "tag": "Create a git tag once publishing succeeds (defaults to true).",
        "tag_prefix": "Prefix to prepend to the git tag name (defaults to 'v').",
        "tag_message": "Custom message for the annotated git tag.",
        "push_tag": "Push the git tag to origin after creation.",
        "force_tag": "Replace an existing git tag with the same name.",
        "commit": "Commit version bump artifacts before building (defaults to true).",
        "commit_message": "Override the git commit message for version bumps.",
    },
)
def release(
    ctx: Context,
    part: str = "patch",
    index_url: str | None = None,
    token: str | None = None,
    skip_existing: bool = False,
    dry_run: bool = False,
    tag: bool = True,
    tag_prefix: str = "v",
    tag_message: str | None = None,
    push_tag: bool = False,
    force_tag: bool = False,
    commit: bool = True,
    commit_message: str | None = None,
) -> None:
    """Bump the version, rebuild artifacts, and publish in one workflow.

    Args:
        ctx: Invoke execution context.
        part: Semantic component to bump prior to publishing.
        index_url: Package index endpoint forwarded to `publish`.
        token: API token forwarded to `publish`.
        skip_existing: Skip previously uploaded artifacts.
        dry_run: Print each command without executing them.
        tag: Create a git tag after publishing when True.
        tag_prefix: Prefix applied to the git tag name.
        tag_message: Annotated git tag message (defaults per tag).
        push_tag: Push the git tag to origin after creation.
        force_tag: Overwrite an existing tag.
        commit: Commit version files prior to building/publishing.
        commit_message: Optional commit message override.
    """
    bump_version(ctx, part=part, dry_run=dry_run)
    if dry_run:
        print("[dry-run] uv build")
        print("[dry-run] uv publish")
        if commit:
            simulated_version = _predict_bumped_version(ctx, part)
            message = commit_message or f"chore: bump version to {simulated_version}"
            print("[dry-run] git add pyproject.toml uv.lock")
            print(f"[dry-run] git commit -m {shlex.quote(message)}")
        if tag:
            simulated_version = _predict_bumped_version(ctx, part)
            tag_name = f"{tag_prefix}{simulated_version}" if tag_prefix else simulated_version
            message = tag_message or f"Release {tag_name}"
            force_flag = " -f" if force_tag else ""
            cmd_preview = (
                f"git tag{force_flag} -a {shlex.quote(tag_name)} -m {shlex.quote(message)}"
            )
            print(f"[dry-run] {cmd_preview}")
            if push_tag:
                print(f"[dry-run] git push origin {shlex.quote(tag_name)}")
        return
    version_after_bump = _get_current_version(ctx)
    if commit:
        message = commit_message or f"chore: bump version to {version_after_bump}"
        _commit_version_files(ctx, ("pyproject.toml", "uv.lock"), message)
    build(ctx)
    publish(ctx, index_url=index_url, token=token, skip_existing=skip_existing)
    if tag:
        tag_version(
            ctx,
            prefix=tag_prefix,
            message=tag_message,
            push=push_tag,
            force=force_tag,
        )


@task(
    help={
        "markers": "Optional pytest marker expression (e.g., smoke).",
        "k": "pytest -k expression for test selection.",
        "path": "Path or module to test (defaults to tests/).",
        "options": "Additional CLI flags forwarded verbatim to pytest.",
    }
)
def tests(
    ctx: Context,
    markers: str = "",
    k: str = "",
    path: str = "tests",
    options: str = "",
) -> None:
    """Run the pytest suite via uv.

    Args:
        ctx: Invoke execution context.
        markers: Marker expression to filter tests.
        k: `pytest -k` expression to select tests.
        path: Target path or dotted module for pytest discovery.
        options: Extra CLI arguments appended to the pytest call.
    """
    args: list[str] = ["run", "pytest"]
    if markers:
        args.extend(["-m", markers])
    if k:
        args.extend(["-k", k])
    if options:
        args.extend(shlex.split(options))
    if path:
        args.append(path)
    _run_uv(ctx, args)


@task(help={"all_files": "Run hooks against the entire repository."})
def precommit(ctx: Context, all_files: bool = False) -> None:
    """Execute the configured pre-commit hooks with uv.

    Args:
        ctx: Invoke execution context.
        all_files: Run hooks against every tracked file rather than diffs.
    """
    args: list[str] = ["run", "pre-commit", "run"]
    if all_files:
        args.append("--all-files")
    _run_uv(ctx, args)


@task(
    help={
        "fix": "Apply auto-fixes where possible (ruff --fix).",
        "check_format": "Run ruff format before linting to enforce formatting.",
    }
)
def lint(ctx: Context, fix: bool = False, check_format: bool = False) -> None:
    """Run Ruff formatting and lint checks via uv.

    Args:
        ctx: Invoke execution context.
        fix: Enable Ruff's fix mode.
        check_format: Run `ruff format --check` before linting.
    """
    if check_format:
        format_args = ["run", "ruff", "format", "--check", "src", "tests"]
        _run_uv(ctx, format_args)
    lint_args: list[str] = ["run", "ruff", "check", "src", "tests"]
    if fix:
        lint_args.append("--fix")
    _run_uv(ctx, lint_args)


@task
def mypy(ctx: Context) -> None:
    """Run MyPy with the project settings via uv.

    Args:
        ctx: Invoke execution context.
    """
    _run_uv(ctx, ["run", "mypy", "src", "main.py"])


@task
def ci(ctx: Context) -> None:
    """Replicate the CI workflow locally via uv.

    Args:
        ctx: Invoke execution context.
    """
    ctx.invoke(lint, check_format=True)
    ctx.invoke(mypy)
    ctx.invoke(tests)


namespace = Collection(
    sync,
    build,
    bump_version,
    publish,
    tag_version,
    release,
    tests,
    precommit,
    lint,
    mypy,
    ci,
)
