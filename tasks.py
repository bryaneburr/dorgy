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

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"


def _run_uv(
    ctx: Context,
    args: Sequence[str],
    *,
    echo: bool = True,
    dry_run: bool = False,
    env: Mapping[str, str] | None = None,
) -> None:
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
        return
    run_env = dict(ctx.config.run.env or {})
    if env:
        run_env.update(env)
    ctx.run(command, echo=echo, pty=True, env=run_env)


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
        "part": "Semantic version component to bump before publishing.",
        "index_url": "Package index endpoint for the publish step.",
        "token": "API token passed to uv publish (printed if provided).",
        "skip_existing": "Skip artifacts already present on the target index.",
        "dry_run": "Log the composed workflow without executing it.",
    },
)
def release(
    ctx: Context,
    part: str = "patch",
    index_url: str | None = None,
    token: str | None = None,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> None:
    """Bump the version, rebuild artifacts, and publish in one workflow.

    Args:
        ctx: Invoke execution context.
        part: Semantic component to bump prior to publishing.
        index_url: Package index endpoint forwarded to `publish`.
        token: API token forwarded to `publish`.
        skip_existing: Skip previously uploaded artifacts.
        dry_run: Print each command without executing them.
    """
    ctx.invoke(bump_version, part=part, dry_run=dry_run)
    if dry_run:
        print("[dry-run] uv build")
        print("[dry-run] uv publish")
        return
    ctx.invoke(build)
    ctx.invoke(publish, index_url=index_url, token=token, skip_existing=skip_existing)


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
    release,
    tests,
    precommit,
    lint,
    mypy,
    ci,
)
