"""Filesystem watch service that reuses the organization pipeline."""

from __future__ import annotations

import queue
import shutil
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:  # pragma: no cover - optional dependency wiring
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # pragma: no cover - fallback when watchdog missing
    Observer = None
    FileSystemEvent = Any  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment]

from dorgy.classification import ClassificationBatch, ClassificationCache
from dorgy.cli_support import (
    build_original_snapshot,
    collect_error_payload,
    compute_org_counts,
    descriptor_to_record,
    relative_to_collection,
    run_classification,
    zip_decisions,
)
from dorgy.config import DorgyConfig
from dorgy.ingestion import IngestionPipeline
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor
from dorgy.ingestion.models import IngestionResult
from dorgy.organization.executor import OperationExecutor
from dorgy.organization.models import OperationPlan
from dorgy.organization.planner import OrganizerPlanner
from dorgy.state import CollectionState, MissingStateError, OperationEvent, StateError, StateRepository


@dataclass(slots=True)
class WatchBatchResult:
    """Outcome metadata describing a processed watch batch.

    Attributes:
        root: Source root that generated the batch.
        target_root: Destination root where organized files reside.
        copy_mode: Indicates whether copy-mode was active.
        dry_run: Indicates whether the batch executed in dry-run mode.
        ingestion: Aggregated ingestion pipeline result.
        classification: Classification batch aligned with descriptors.
        plan: Operation plan constructed for the batch.
        events: History events persisted after applying operations.
        counts: Summary metrics such as processed files and conflicts.
        errors: Structured ingestion/classification error payloads.
        json_payload: JSON-ready payload mirroring CLI outputs.
        notes: Planner notes surfaced during plan construction.
        quarantine_paths: Paths that were moved into quarantine.
        triggered_paths: Paths that triggered the batch run.
    """

    root: Path
    target_root: Path
    copy_mode: bool
    dry_run: bool
    ingestion: IngestionResult
    classification: ClassificationBatch
    plan: OperationPlan
    events: list[OperationEvent]
    counts: dict[str, int]
    errors: dict[str, list[str]]
    json_payload: dict[str, Any]
    notes: list[str]
    quarantine_paths: list[Path]
    triggered_paths: list[Path]


class WatchService:
    """High-level orchestration layer for directory monitoring."""

    def __init__(
        self,
        config: DorgyConfig,
        *,
        roots: Iterable[Path],
        prompt: Optional[str],
        output: Optional[Path],
        dry_run: bool,
        recursive: bool,
        debounce_override: Optional[float] = None,
    ) -> None:
        """Initialize the watch service.

        Args:
            config: Loaded Dorgy configuration.
            roots: Iterable of directory roots to monitor.
            prompt: Optional classification prompt override.
            output: Optional destination root when operating in copy-mode.
            dry_run: Whether to avoid filesystem mutations.
            recursive: Whether to monitor subdirectories.
            debounce_override: Optional debounce interval override in seconds.
        """

        self._config = config
        self._prompt = prompt
        self._roots = [root.expanduser().resolve() for root in roots]
        self._output = output.expanduser().resolve() if output else None
        self._dry_run = dry_run
        self._recursive = recursive
        self._repository = StateRepository()
        self._observer: object | None = None
        self._queue: queue.Queue[tuple[Path | None, Path | None]] = queue.Queue()
        self._stop_event = threading.Event()
        self._pending_lock = threading.Lock()
        self._classification_caches: dict[Path, ClassificationCache] = {}
        self._batch_counter = 0
        self._watch_settings = config.processing.watch
        self._debounce_seconds = (
            max(0.1, debounce_override)
            if debounce_override and debounce_override > 0
            else max(0.1, self._watch_settings.debounce_seconds)
        )
        self._max_batch_items = max(1, self._watch_settings.max_batch_items)
        self._max_batch_interval = (
            self._watch_settings.max_batch_interval_seconds
            if self._watch_settings.max_batch_interval_seconds > 0
            else None
        )
        self._initial_backoff = max(0.1, self._watch_settings.error_backoff_seconds)
        self._max_backoff = max(self._initial_backoff, self._watch_settings.max_error_backoff_seconds)
        self._backoff: dict[Path, float] = defaultdict(lambda: self._initial_backoff)
        self._copy_mode = False
        if self._output is not None:
            if len(self._roots) != 1:
                raise ValueError("--output requires a single source root.")
            self._copy_mode = True

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #

    def process_once(self) -> list[WatchBatchResult]:
        """Process configured roots once.

        Returns:
            list[WatchBatchResult]: Results produced for roots that yielded work.
        """

        results: list[WatchBatchResult] = []
        for root in self._roots:
            batch = self._run_batch(root, [root])
            if batch is not None:
                results.append(batch)
        return results

    def watch(self, callback: Callable[[WatchBatchResult], None]) -> None:
        """Start processing filesystem events.

        Args:
            callback: Callable invoked with each completed batch result.
        """

        if Observer is None:
            raise RuntimeError(
                "watchdog is required for continuous watch mode. Install it via `uv pip install watchdog`."
            )

        if self._observer is not None:
            raise RuntimeError("WatchService is already running.")

        self._observer = Observer()
        for root in self._roots:
            handler = _WatchEventHandler(root, self._queue, self._repository.base_dirname)
            self._observer.schedule(handler, str(root), recursive=self._recursive)

        self._observer.start()
        try:
            self._run_loop(callback)
        finally:
            self.stop()

    def stop(self) -> None:
        """Terminate the watch service and release resources.

        Returns:
            None: This method stops the observer and clears pending queues.
        """

        self._stop_event.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        # Unblock the queue to allow the processing loop to exit cleanly.
        self._queue.put((None, None))

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _run_loop(self, callback: Callable[[WatchBatchResult], None]) -> None:
        """Consume queued filesystem events and dispatch batches.

        Args:
            callback: Callable invoked for each processed batch.
        """
        pending: dict[Path, set[Path]] = defaultdict(set)
        batch_started_at: Optional[float] = None
        flush_deadline: Optional[float] = None

        while not self._stop_event.is_set():
            timeout: Optional[float] = None
            if flush_deadline is not None:
                timeout = max(0.0, flush_deadline - time.monotonic())

            try:
                root, path = self._queue.get(timeout=timeout)
            except queue.Empty:
                if pending:
                    self._flush_batches(pending, callback)
                    pending.clear()
                    batch_started_at = None
                    flush_deadline = None
                continue

            if root is None or path is None:
                break

            if not path.exists() and not path.is_file():
                continue
            if self._repository.base_dirname in path.parts:
                continue

            pending[root].add(path)
            now = time.monotonic()
            if batch_started_at is None:
                batch_started_at = now
            flush_deadline = now + self._debounce_seconds
            total_items = sum(len(paths) for paths in pending.values())
            if total_items >= self._max_batch_items:
                self._flush_batches(pending, callback)
                pending.clear()
                batch_started_at = None
                flush_deadline = None
                continue

            if self._max_batch_interval is not None and (now - batch_started_at) >= self._max_batch_interval:
                self._flush_batches(pending, callback)
                pending.clear()
                batch_started_at = None
                flush_deadline = None

    def _flush_batches(
        self,
        pending: dict[Path, set[Path]],
        callback: Callable[[WatchBatchResult], None],
    ) -> None:
        """Flush pending paths by executing the organization pipeline.

        Args:
            pending: Mapping of roots to candidate paths awaiting processing.
            callback: Callable used to surface completed batch results.
        """
        for root, paths in list(pending.items()):
            if not paths:
                continue
            triggered = sorted(paths)
            try:
                batch = self._run_batch(root, triggered)
            except Exception as exc:  # pragma: no cover - defensive branch
                self._log_failure(root, triggered, exc)
                backoff = self._backoff[root]
                time.sleep(backoff)
                self._backoff[root] = min(backoff * 2, self._max_backoff)
                continue

            self._backoff[root] = self._initial_backoff
            if batch is not None:
                callback(batch)

    def _run_batch(self, root: Path, paths: Iterable[Path]) -> Optional[WatchBatchResult]:
        """Execute ingestion, classification, and organization for a batch.

        Args:
            root: Monitored root producing the batch.
            paths: Candidate paths that triggered the batch.

        Returns:
            Optional[WatchBatchResult]: Populated batch result, or ``None`` when no
            descriptors were produced.
        """
        candidates = [path for path in paths if path.exists() or path.is_file()]
        if not candidates:
            return None

        source_root = root
        target_root = self._output if self._output is not None else source_root

        if not self._dry_run:
            target_root.mkdir(parents=True, exist_ok=True)

        state_dir = target_root / self._repository.base_dirname
        staging_dir = None if self._dry_run else state_dir / "staging"

        cache = self._classification_caches.get(source_root)
        if cache is None:
            cache_path = state_dir / "classifications.json"
            cache = ClassificationCache(cache_path)
            self._classification_caches[source_root] = cache

        max_size_bytes = None
        if self._config.processing.max_file_size_mb > 0:
            max_size_bytes = self._config.processing.max_file_size_mb * 1024 * 1024

        scanner = DirectoryScanner(
            recursive=self._recursive or self._config.processing.recurse_directories,
            include_hidden=self._config.processing.process_hidden_files,
            follow_symlinks=self._config.processing.follow_symlinks,
            max_size_bytes=max_size_bytes,
        )

        pipeline = IngestionPipeline(
            scanner=scanner,
            detector=TypeDetector(),
            hasher=HashComputer(),
            extractor=MetadataExtractor(),
            processing=self._config.processing,
            staging_dir=staging_dir,
            allow_writes=not self._dry_run,
        )

        result = pipeline.run(candidates)
        classification_batch = run_classification(
            result.processed,
            self._prompt,
            source_root,
            self._dry_run,
            self._config,
            cache,
        )

        paired = list(zip_decisions(classification_batch, result.processed))
        confidence_threshold = self._config.ambiguity.confidence_threshold
        for decision, descriptor in paired:
            if decision is not None and decision.confidence < confidence_threshold:
                decision.needs_review = True
                if descriptor.path not in result.needs_review:
                    result.needs_review.append(descriptor.path)

        planner = OrganizerPlanner()
        plan = planner.build_plan(
            descriptors=[descriptor for _, descriptor in paired],
            decisions=[decision for decision, _ in paired],
            rename_enabled=self._config.organization.rename_files,
            root=target_root,
            conflict_strategy=self._config.organization.conflict_resolution,
        )

        rename_map = {operation.source: operation.destination for operation in plan.renames}
        move_map = {operation.source: operation.destination for operation in plan.moves}
        final_path_map: dict[Path, Path] = {}

        file_entries: list[dict[str, Any]] = []

        for decision, descriptor in paired:
            original_path = descriptor.path
            rename_target = rename_map.get(original_path)
            move_key = rename_target if rename_target is not None else original_path
            move_target = move_map.get(move_key)
            final_path = move_target or rename_target or original_path
            final_path_map[original_path] = final_path

            file_entries.append(
                {
                    "original_path": original_path.as_posix(),
                    "final_path": final_path.as_posix(),
                    "descriptor": descriptor.model_dump(mode="json"),
                    "classification": decision.model_dump(mode="json") if decision else None,
                    "operations": {
                        "rename": rename_target.as_posix() if rename_target else None,
                        "move": move_target.as_posix() if move_target else None,
                    },
                }
            )

        counts = compute_org_counts(result, classification_batch, plan)
        errors = collect_error_payload(result, classification_batch)

        batch_id = self._next_batch_id()
        json_payload: dict[str, Any] = {
            "context": {
                "batch_id": batch_id,
                "source_root": source_root.as_posix(),
                "destination_root": target_root.as_posix(),
                "copy_mode": self._copy_mode,
                "dry_run": self._dry_run,
                "prompt": self._prompt,
                "triggered_paths": [path.as_posix() for path in candidates],
            },
            "counts": counts,
            "plan": plan.model_dump(mode="json"),
            "files": file_entries,
            "notes": list(plan.notes),
            "errors": errors,
        }

        if self._dry_run:
            return WatchBatchResult(
                root=source_root,
                target_root=target_root,
                copy_mode=self._copy_mode,
                dry_run=True,
                ingestion=result,
                classification=classification_batch,
                plan=plan,
                events=[],
                counts=counts,
                errors=errors,
                json_payload=json_payload,
                notes=list(plan.notes),
                quarantine_paths=[],
                triggered_paths=[path for path in candidates],
            )

        state_dir = self._repository.initialize(target_root)
        quarantine_dir = state_dir / "quarantine"
        if result.quarantined and self._config.processing.corrupted_files.action == "quarantine":
            moved_paths: list[Path] = []
            for original in result.quarantined:
                target = quarantine_dir / original.name
                counter = 1
                while target.exists():
                    target = target.with_name(f"{original.stem}-{counter}{original.suffix}")
                    counter += 1
                try:
                    shutil.move(str(original), str(target))
                except OSError:
                    continue
                moved_paths.append(target)
            result.quarantined = moved_paths

        try:
            state = self._repository.load(target_root)
        except MissingStateError:
            state = CollectionState(root=str(target_root))

        snapshot = build_original_snapshot([descriptor for _, descriptor in paired], source_root)
        try:
            existing_snapshot = self._repository.load_original_structure(target_root) or {"entries": []}
        except StateError:
            existing_snapshot = {"entries": []}
        existing_entries = {
            entry["path"]: entry
            for entry in existing_snapshot.get("entries", [])
            if isinstance(entry, dict) and "path" in entry
        }
        for entry in snapshot.get("entries", []):
            key = entry.get("path")
            if key is None:
                continue
            existing_entries.setdefault(key, entry)
        merged_snapshot = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entries": list(existing_entries.values()),
        }
        self._repository.write_original_structure(target_root, merged_snapshot)

        executor = OperationExecutor(
            staging_root=state_dir / "staging",
            copy_mode=self._copy_mode,
            source_root=source_root,
        )

        events: list[OperationEvent] = executor.apply(plan, target_root)

        for decision, descriptor in paired:
            original_path = descriptor.path
            final_path = final_path_map.get(original_path, original_path)
            old_relative = relative_to_collection(original_path, target_root)

            descriptor.path = final_path
            descriptor.display_name = descriptor.path.name

            record = descriptor_to_record(descriptor, decision, target_root)

            state.files.pop(old_relative, None)
            state.files[record.path] = record

        self._repository.save(target_root, state)
        if events:
            self._repository.append_history(target_root, events)

        log_path = state_dir / "watch.log"
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                timestamp = datetime.now(timezone.utc).isoformat()
                log_file.write(
                    f"[{timestamp}] batch={batch_id} processed={len(result.processed)} "
                    f"needs_review={len(result.needs_review)} quarantined={len(result.quarantined)} "
                    f"renames={len(plan.renames)} moves={len(plan.moves)} "
                    f"errors={len(result.errors) + len(classification_batch.errors)}\n"
                )
                for error in result.errors:
                    log_file.write(f"  error: {error}\n")
                for error in classification_batch.errors:
                    log_file.write(f"  classification_error: {error}\n")
                for renamed in plan.renames:
                    log_file.write(f"  rename: {renamed.source} -> {renamed.destination}\n")
                for moved in plan.moves:
                    log_file.write(f"  move: {moved.source} -> {moved.destination}\n")
        except OSError:
            pass

        json_payload["history"] = [event.model_dump(mode="json") for event in events]
        json_payload["state"] = {
            "path": str(state_dir / "state.json"),
            "files_tracked": len(state.files),
        }
        json_payload["log_path"] = str(log_path)
        json_payload["quarantine"] = [path.as_posix() for path in result.quarantined]

        return WatchBatchResult(
            root=source_root,
            target_root=target_root,
            copy_mode=self._copy_mode,
            dry_run=False,
            ingestion=result,
            classification=classification_batch,
            plan=plan,
            events=events,
            counts=counts,
            errors=errors,
            json_payload=json_payload,
            notes=list(plan.notes),
            quarantine_paths=list(result.quarantined),
            triggered_paths=[path for path in candidates],
        )

    def _next_batch_id(self) -> int:
        """Return the next batch identifier."""
        self._batch_counter += 1
        return self._batch_counter

    def _log_failure(self, root: Path, paths: Iterable[Path], exc: Exception) -> None:
        """Persist a failure entry to the watch log.

        Args:
            root: Root being processed when the failure occurred.
            paths: Paths that triggered the batch.
            exc: Exception detailing the failure.
        """
        if self._dry_run:
            return
        target_root = self._output if self._output is not None else root
        state_dir = target_root / self._repository.base_dirname
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            with (state_dir / "watch.log").open("a", encoding="utf-8") as log_file:
                timestamp = datetime.now(timezone.utc).isoformat()
                joined = ", ".join(path.as_posix() for path in paths)
                log_file.write(
                    f"[{timestamp}] batch_error paths=[{joined}] error={exc.__class__.__name__}: {exc}\n"
                )
        except OSError:
            pass


class _WatchEventHandler(FileSystemEventHandler):
    """Forward filesystem events into the service queue."""

    def __init__(
        self,
        root: Path,
        queue_handle: queue.Queue[tuple[Path | None, Path | None]],
        state_dirname: str,
    ) -> None:
        self._root = root
        self._queue = queue_handle
        self._state_dirname = state_dirname

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle a filesystem create event."""
        self._enqueue(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle a filesystem modify event."""
        self._enqueue(event)

    def on_moved(self, event: FileSystemEvent) -> None:  # pragma: no cover - watchdog-specific
        """Handle a filesystem move event."""
        self._enqueue(event)

    def _enqueue(self, event: FileSystemEvent) -> None:
        """Queue filesystem events for downstream processing."""
        if event.is_directory:
            return
        path = Path(event.src_path).expanduser()
        if self._state_dirname in path.parts:
            return
        self._queue.put((self._root, path))
