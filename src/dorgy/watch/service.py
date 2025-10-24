"""Filesystem watch service that reuses the organization pipeline."""

from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Literal, Optional, cast

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
else:  # pragma: no cover - runtime optional dependency wiring
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        FileSystemEvent = cast(Any, object)  # type: ignore[assignment]
        FileSystemEventHandler = cast(Any, object)  # type: ignore[assignment]
        Observer = cast(Any, None)  # type: ignore[assignment]

from dorgy.classification import (
    ClassificationBatch,
    ClassificationCache,
    VisionCache,
    VisionCaptioner,
)
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
from dorgy.organization.models import DeleteOperation, OperationPlan
from dorgy.organization.planner import OrganizerPlanner
from dorgy.shutdown import ShutdownRequested, check_for_shutdown, shutdown_requested
from dorgy.state import (
    CollectionState,
    MissingStateError,
    OperationEvent,
    StateError,
    StateRepository,
)

LOGGER = logging.getLogger(__name__)


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
        delete_operations: Delete operations generated for this batch.
        suppressed_deletions: Deletion candidates skipped due to configuration or dry-run.
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
    delete_operations: list[DeleteOperation]
    suppressed_deletions: list[dict[str, str]]


@dataclass(slots=True)
class WatchEvent:
    """Normalized filesystem event consumed by the watch service.

    Attributes:
        kind: Event classification (`scan`, `created`, `modified`, `deleted`, or `moved`).
        src: Source path associated with the event.
        dest: Optional destination path for move events.
        timestamp: Event timestamp in UTC.
    """

    kind: Literal["scan", "created", "modified", "deleted", "moved"]
    src: Path
    dest: Path | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class RemovalRequest:
    """Intermediate representation describing a potential state removal.

    Attributes:
        path: Original file path tracked within the collection root.
        destination: Optional destination path when the file was moved.
        reason: Human-readable reason for the removal.
        kind: Removal category (`deleted`, `moved_out`, or `moved_within`).
    """

    path: Path
    destination: Path | None
    reason: str
    kind: Literal["deleted", "moved_out", "moved_within"]

    @property
    def requires_confirmation(self) -> bool:
        """Return whether this removal requires deletion opt-in safeguards."""

        return self.kind != "moved_within"


class WatchService:
    """High-level orchestration layer for directory monitoring."""

    def __init__(
        self,
        config: DorgyConfig,
        *,
        roots: Iterable[Path],
        classification_prompt: Optional[str],
        structure_prompt: Optional[str],
        output: Optional[Path],
        dry_run: bool,
        recursive: bool,
        debounce_override: Optional[float] = None,
        allow_deletions: bool = False,
    ) -> None:
        """Initialize the watch service.

        Args:
            config: Loaded Dorgy configuration.
            roots: Iterable of directory roots to monitor.
            classification_prompt: Optional classification prompt override.
            structure_prompt: Optional structure planning prompt override.
            output: Optional destination root when operating in copy-mode.
            dry_run: Whether to avoid filesystem mutations.
            recursive: Whether to monitor subdirectories.
            debounce_override: Optional debounce interval override in seconds.
            allow_deletions: Whether to remove records when files are deleted or
                moved outside monitored roots.
        """

        self._config = config
        self._classification_prompt = classification_prompt
        self._structure_prompt = structure_prompt or classification_prompt
        self._roots = [root.expanduser().resolve() for root in roots]
        self._output = output.expanduser().resolve() if output else None
        self._dry_run = dry_run
        self._recursive = recursive
        self._repository = StateRepository()
        self._observer: Any = None
        self._queue: queue.Queue[tuple[Path | None, WatchEvent | None]] = queue.Queue()
        self._stop_event = threading.Event()
        self._pending_lock = threading.Lock()
        self._classification_caches: dict[Path, ClassificationCache] = {}
        self._vision_caches: dict[Path, VisionCache] = {}
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
        self._max_backoff = max(
            self._initial_backoff, self._watch_settings.max_error_backoff_seconds
        )
        self._backoff: dict[Path, float] = defaultdict(lambda: self._initial_backoff)
        self._copy_mode = False
        self._allow_deletions = allow_deletions
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

        check_for_shutdown()
        results: list[WatchBatchResult] = []
        for root in self._roots:
            check_for_shutdown()
            batch = self._run_batch(root, [WatchEvent(kind="scan", src=root)])
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
                "watchdog is required for continuous watch mode. "
                "Install it via `uv pip install watchdog`."
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
        pending: dict[Path, list[WatchEvent]] = defaultdict(list)
        batch_started_at: Optional[float] = None
        flush_deadline: Optional[float] = None

        while not self._stop_event.is_set():
            if shutdown_requested():
                self.stop()
                break
            timeout: Optional[float] = None
            if flush_deadline is not None:
                timeout = max(0.0, flush_deadline - time.monotonic())

            try:
                root, event = self._queue.get(timeout=timeout)
            except queue.Empty:
                if pending:
                    self._flush_batches(pending, callback)
                    pending.clear()
                    batch_started_at = None
                    flush_deadline = None
                continue

            if root is None or event is None:
                break

            pending[root].append(event)
            now = time.monotonic()
            if batch_started_at is None:
                batch_started_at = now
            flush_deadline = now + self._debounce_seconds
            total_items = sum(len(events) for events in pending.values())
            if total_items >= self._max_batch_items:
                self._flush_batches(pending, callback)
                pending.clear()
                batch_started_at = None
                flush_deadline = None
                continue

            if (
                self._max_batch_interval is not None
                and (now - batch_started_at) >= self._max_batch_interval
            ):
                self._flush_batches(pending, callback)
                pending.clear()
                batch_started_at = None
                flush_deadline = None

    def _flush_batches(
        self,
        pending: dict[Path, list[WatchEvent]],
        callback: Callable[[WatchBatchResult], None],
    ) -> None:
        """Flush pending events by executing the organization pipeline.

        Args:
            pending: Mapping of roots to pending watch events awaiting processing.
            callback: Callable used to surface completed batch results.
        """
        check_for_shutdown()
        for root, events in list(pending.items()):
            if not events:
                continue
            triggered = list(events)
            try:
                check_for_shutdown()
                batch = self._run_batch(root, triggered)
            except ShutdownRequested:
                self.stop()
                raise
            except Exception as exc:  # pragma: no cover - defensive branch
                self._log_failure(root, [event.src for event in triggered], exc)
                backoff = self._backoff[root]
                time.sleep(backoff)
                self._backoff[root] = min(backoff * 2, self._max_backoff)
                continue

            self._backoff[root] = self._initial_backoff
            if batch is not None:
                callback(batch)

    def _run_batch(
        self, root: Path, watch_events: Iterable[WatchEvent]
    ) -> Optional[WatchBatchResult]:
        """Execute ingestion, classification, and organization for a batch.

        Args:
            root: Monitored root producing the batch.
            watch_events: Filesystem events that triggered the batch.

        Returns:
            Optional[WatchBatchResult]: Populated batch result, or ``None`` when no
            work was required.
        """
        check_for_shutdown()
        event_list = list(watch_events)
        if not event_list:
            return None

        batch_started_at = datetime.now(timezone.utc)
        source_root = root
        target_root = self._output if self._output is not None else source_root

        if not self._dry_run:
            target_root.mkdir(parents=True, exist_ok=True)

        state_dir = target_root / self._repository.base_dirname
        staging_dir = None if self._dry_run else state_dir / "staging"

        triggered_paths_set: set[Path] = set()
        ingestion_candidates: set[Path] = set()
        removal_requests: dict[Path, RemovalRequest] = {}

        for event in event_list:
            if not self._should_ignore_path(event.src):
                triggered_paths_set.add(event.src)
            if event.dest is not None and not self._should_ignore_path(event.dest):
                triggered_paths_set.add(event.dest)

            if event.kind == "scan":
                ingestion_candidates.add(event.src)
                continue

            if event.kind in {"created", "modified"}:
                candidate = event.src
                if not self._should_ignore_path(candidate) and candidate.exists():
                    ingestion_candidates.add(candidate)
                continue

            if event.kind == "deleted":
                src_within = self._is_within_root(event.src, source_root)
                if src_within and not self._should_ignore_path(event.src):
                    removal_requests[event.src] = RemovalRequest(
                        path=event.src,
                        destination=None,
                        reason="Filesystem reported deletion inside watched root.",
                        kind="deleted",
                    )
                continue

            if event.kind == "moved":
                dest = event.dest
                src_within = self._is_within_root(event.src, source_root)
                dest_within = dest is not None and self._is_within_root(dest, source_root)
                if (
                    dest_within
                    and dest is not None
                    and not self._should_ignore_path(dest)
                    and dest.exists()
                ):
                    ingestion_candidates.add(dest)
                if not src_within or self._should_ignore_path(event.src):
                    continue
                if dest_within and dest is not None and not self._should_ignore_path(dest):
                    removal_requests[event.src] = RemovalRequest(
                        path=event.src,
                        destination=dest,
                        reason=f"File moved within watched root to {dest.name}.",
                        kind="moved_within",
                    )
                else:
                    reason = "File moved outside watched roots."
                    if dest is not None:
                        reason = f"File moved outside watched roots to {dest}."
                    removal_requests[event.src] = RemovalRequest(
                        path=event.src,
                        destination=dest,
                        reason=reason,
                        kind="moved_out",
                    )
                continue

        ingestion_inputs = sorted(ingestion_candidates)
        if not ingestion_inputs and not removal_requests:
            return None

        result = IngestionResult()
        classification_batch = ClassificationBatch()
        paired: list[tuple[Any, Any]] = []
        planner = OrganizerPlanner()
        plan = OperationPlan()
        final_path_map: dict[Path, Path] = {}
        file_entries: list[dict[str, Any]] = []
        vision_warning: str | None = None

        if ingestion_inputs:
            cache = self._classification_caches.get(source_root)
            if cache is None:
                cache_path = state_dir / "classifications.json"
                cache = ClassificationCache(cache_path)
                self._classification_caches[source_root] = cache

            vision_cache: VisionCache | None = None
            vision_captioner: VisionCaptioner | None = None
            if self._config.processing.process_images:
                vision_cache = self._vision_caches.get(source_root)
                if vision_cache is None:
                    vision_cache = VisionCache(state_dir / "vision.json")
                    vision_cache.load()
                    self._vision_caches[source_root] = vision_cache
                try:
                    vision_captioner = VisionCaptioner(self._config.llm, cache=vision_cache)
                except RuntimeError as exc:
                    vision_warning = f"Vision captioning disabled: {exc}"
                    LOGGER.warning("%s", vision_warning)
                    vision_captioner = None

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
                extractor=MetadataExtractor(
                    preview_char_limit=self._config.processing.preview_char_limit
                ),
                processing=self._config.processing,
                staging_dir=staging_dir,
                allow_writes=not self._dry_run,
                vision_captioner=vision_captioner,
            )

            check_for_shutdown()
            result = pipeline.run(ingestion_inputs, prompt=self._classification_prompt)
            if not self._dry_run and vision_captioner is not None:
                vision_captioner.save_cache()
            parallel_workers = max(1, self._config.processing.parallel_workers)
            check_for_shutdown()
            classification_batch = run_classification(
                result.processed,
                classification_prompt=self._classification_prompt,
                root=source_root,
                dry_run=self._dry_run,
                config=self._config,
                cache=cache,
                on_progress=None,
                max_workers=parallel_workers,
            )

            paired = list(zip_decisions(classification_batch, result.processed))
            confidence_threshold = self._config.ambiguity.confidence_threshold
            for decision, descriptor in paired:
                check_for_shutdown()
                if decision is not None and decision.confidence < confidence_threshold:
                    decision.needs_review = True
                    if descriptor.path not in result.needs_review:
                        result.needs_review.append(descriptor.path)

            plan = planner.build_plan(
                descriptors=[descriptor for _, descriptor in paired],
                decisions=[decision for decision, _ in paired],
                rename_enabled=self._config.organization.rename_files,
                root=target_root,
                conflict_strategy=self._config.organization.conflict_resolution,
            )

            rename_map = {operation.source: operation.destination for operation in plan.renames}
            move_map = {operation.source: operation.destination for operation in plan.moves}

            for decision, descriptor in paired:
                check_for_shutdown()
                original_path = descriptor.path
                rename_target = rename_map.get(original_path)
                move_key = rename_target if rename_target is not None else original_path
                move_target = move_map.get(move_key)
                final_path = move_target or rename_target or original_path
                final_path_map[original_path] = final_path

                vision_metadata: dict[str, Any] | None = None
                if self._config.processing.process_images and descriptor.metadata.get(
                    "vision_caption"
                ):
                    vision_metadata = {
                        "caption": descriptor.metadata.get("vision_caption"),
                        "labels": descriptor.metadata.get("vision_labels"),
                        "confidence": descriptor.metadata.get("vision_confidence"),
                        "reasoning": descriptor.metadata.get("vision_reasoning"),
                    }

                file_entries.append(
                    {
                        "original_path": original_path.as_posix(),
                        "final_path": final_path.as_posix(),
                        "descriptor": descriptor.model_dump(mode="json"),
                        "classification": decision.model_dump(mode="json") if decision else None,
                        "vision": vision_metadata,
                        "operations": {
                            "rename": rename_target.as_posix() if rename_target else None,
                            "move": move_target.as_posix() if move_target else None,
                        },
                    }
                )
        else:
            plan = planner.build_plan(
                descriptors=[],
                decisions=[],
                rename_enabled=self._config.organization.rename_files,
                root=target_root,
                conflict_strategy=self._config.organization.conflict_resolution,
            )

        if vision_warning:
            plan.notes.append(vision_warning)

        delete_operations = [
            DeleteOperation(
                path=request.path,
                reason=request.reason,
                destination=request.destination,
                kind=request.kind,
            )
            for request in removal_requests.values()
        ]
        if delete_operations:
            plan.deletes.extend(delete_operations)

        counts = compute_org_counts(result, classification_batch, plan)
        errors = collect_error_payload(result, classification_batch)

        triggered_paths = sorted(triggered_paths_set)
        batch_id = self._next_batch_id()
        notes = list(plan.notes)

        executed_requests: list[RemovalRequest] = []
        suppressed_requests: list[tuple[RemovalRequest, str]] = []
        for request in removal_requests.values():
            if self._dry_run:
                suppressed_requests.append((request, "dry_run"))
                continue
            if request.requires_confirmation and not self._allow_deletions:
                suppressed_requests.append((request, "config"))
                continue
            executed_requests.append(request)

        operations_by_path = {operation.path: operation for operation in delete_operations}
        executed_delete_ops = [
            operations_by_path[request.path]
            for request in executed_requests
            if request.path in operations_by_path
        ]

        counts["deletes"] = len(executed_delete_ops)

        removals_payload: list[dict[str, Any]] = []
        for delete_operation in delete_operations:
            matching_request = removal_requests.get(delete_operation.path)
            request_kind: str | None = (
                matching_request.kind if matching_request is not None else None
            )
            executed = delete_operation in executed_delete_ops
            removals_payload.append(
                {
                    "path": relative_to_collection(delete_operation.path, target_root),
                    "reason": delete_operation.reason,
                    "destination": delete_operation.destination.as_posix()
                    if delete_operation.destination
                    else None,
                    "executed": executed,
                    "kind": request_kind,
                }
            )

        suppressed_payload: list[dict[str, str]] = []
        for request, cause in suppressed_requests:
            suppressed_payload.append(
                {
                    "path": relative_to_collection(request.path, target_root),
                    "reason": request.reason,
                    "cause": cause,
                    "destination": request.destination.as_posix() if request.destination else "",
                    "kind": request.kind,
                }
            )

        if suppressed_requests:
            config_suppressed = [req for req, cause in suppressed_requests if cause == "config"]
            dryrun_suppressed = [req for req, cause in suppressed_requests if cause == "dry_run"]
            if config_suppressed:
                relative_list = ", ".join(
                    sorted(
                        relative_to_collection(req.path, target_root) for req in config_suppressed
                    )
                )
                config_message = (
                    f"Suppressed {len(config_suppressed)} deletion(s); "
                    "enable processing.watch.allow_deletions or pass --allow-deletions "
                    f"to remove: {relative_list}"
                )
                notes.append(config_message)
            if dryrun_suppressed:
                relative_list = ", ".join(
                    sorted(
                        relative_to_collection(req.path, target_root) for req in dryrun_suppressed
                    )
                )
                dryrun_message = (
                    f"Dry-run prevented applying {len(dryrun_suppressed)} deletion(s): "
                    f"{relative_list}"
                )
                notes.append(dryrun_message)

        llm_metadata = self._config.llm.runtime_metadata()
        fallbacks_enabled = os.getenv("DORGY_USE_FALLBACKS") == "1"
        llm_metadata["fallbacks_enabled"] = fallbacks_enabled
        fallback_text = "enabled" if fallbacks_enabled else "disabled"
        llm_metadata["summary"] = f"{self._config.llm.runtime_summary()}, fallbacks={fallback_text}"

        json_payload: dict[str, Any] = {
            "context": {
                "batch_id": batch_id,
                "source_root": source_root.as_posix(),
                "destination_root": target_root.as_posix(),
                "copy_mode": self._copy_mode,
                "dry_run": self._dry_run,
                "classification_prompt": self._classification_prompt,
                "structure_prompt": self._structure_prompt,
                # Backwards compatibility: retain legacy key.
                "prompt": self._classification_prompt,
                "allow_deletions": self._allow_deletions,
                "triggered_paths": [path.as_posix() for path in triggered_paths],
                "started_at": batch_started_at.isoformat(),
            },
            "counts": counts,
            "plan": plan.model_dump(mode="json"),
            "files": file_entries,
            "notes": notes,
            "errors": errors,
            "removals": removals_payload,
            "suppressed_deletions": suppressed_payload,
        }
        json_payload["context"]["llm"] = llm_metadata

        if self._dry_run:
            batch_completed_at = datetime.now(timezone.utc)
            duration_seconds = round((batch_completed_at - batch_started_at).total_seconds(), 3)
            json_payload["context"]["completed_at"] = batch_completed_at.isoformat()
            json_payload["context"]["duration_seconds"] = duration_seconds
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
                notes=notes,
                quarantine_paths=[],
                triggered_paths=triggered_paths,
                delete_operations=list(delete_operations),
                suppressed_deletions=suppressed_payload,
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
            existing_snapshot = self._repository.load_original_structure(target_root) or {
                "entries": []
            }
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

        operation_events: list[OperationEvent] = executor.apply(plan, target_root)

        for decision, descriptor in paired:
            original_path = descriptor.path
            final_path = final_path_map.get(original_path, original_path)
            old_relative = relative_to_collection(original_path, target_root)

            descriptor.path = final_path
            descriptor.display_name = descriptor.path.name

            record = descriptor_to_record(descriptor, decision, target_root)

            state.files.pop(old_relative, None)
            state.files[record.path] = record

        removed_relatives: list[str] = []
        for request in executed_requests:
            relative = relative_to_collection(request.path, target_root)
            if state.files.pop(relative, None) is not None:
                removed_relatives.append(relative)

        delete_events: list[OperationEvent] = []
        for request in executed_requests:
            matched_operation: DeleteOperation | None = operations_by_path.get(request.path)
            destination_path = (
                matched_operation.destination
                if matched_operation is not None
                else request.destination
            )
            delete_events.append(
                OperationEvent(
                    timestamp=datetime.now(timezone.utc),
                    operation="delete",
                    source=relative_to_collection(request.path, target_root),
                    destination=relative_to_collection(destination_path, target_root)
                    if destination_path is not None
                    else None,
                    notes=[request.reason],
                )
            )

        operation_events.extend(delete_events)

        self._repository.save(target_root, state)
        if operation_events:
            self._repository.append_history(target_root, operation_events)

        log_path = state_dir / "watch.log"
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                timestamp = datetime.now(timezone.utc).isoformat()
                summary_line = (
                    f"[{timestamp}] batch={batch_id} processed={len(result.processed)} "
                    f"needs_review={len(result.needs_review)} "
                    f"quarantined={len(result.quarantined)} "
                    f"renames={len(plan.renames)} "
                    f"moves={len(plan.moves)} "
                    f"deletes={len(executed_delete_ops)} "
                    f"errors={len(result.errors) + len(classification_batch.errors)}\n"
                )
                log_file.write(summary_line)
                for error in result.errors:
                    log_file.write(f"  error: {error}\n")
                for error in classification_batch.errors:
                    log_file.write(f"  classification_error: {error}\n")
                for renamed in plan.renames:
                    log_file.write(f"  rename: {renamed.source} -> {renamed.destination}\n")
                for moved in plan.moves:
                    log_file.write(f"  move: {moved.source} -> {moved.destination}\n")
                for delete_op in executed_delete_ops:
                    destination = (
                        delete_op.destination.as_posix()
                        if delete_op.destination is not None
                        else "<removed>"
                    )
                    delete_line = (
                        f"  delete[{delete_op.kind}]: {delete_op.path.as_posix()} -> "
                        f"{destination}\n"
                    )
                    log_file.write(delete_line)
        except OSError:
            pass

        json_payload["history"] = [event.model_dump(mode="json") for event in operation_events]
        json_payload["state"] = {
            "path": str(state_dir / "state.json"),
            "files_tracked": len(state.files),
        }
        json_payload["log_path"] = str(log_path)
        json_payload["quarantine"] = [path.as_posix() for path in result.quarantined]
        json_payload["removed_records"] = removed_relatives

        batch_completed_at = datetime.now(timezone.utc)
        duration_seconds = round((batch_completed_at - batch_started_at).total_seconds(), 3)
        json_payload["context"]["completed_at"] = batch_completed_at.isoformat()
        json_payload["context"]["duration_seconds"] = duration_seconds

        return WatchBatchResult(
            root=source_root,
            target_root=target_root,
            copy_mode=self._copy_mode,
            dry_run=False,
            ingestion=result,
            classification=classification_batch,
            plan=plan,
            events=operation_events,
            counts=counts,
            errors=errors,
            json_payload=json_payload,
            notes=notes,
            quarantine_paths=list(result.quarantined),
            triggered_paths=triggered_paths,
            delete_operations=list(delete_operations),
            suppressed_deletions=suppressed_payload,
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
                error_line = (
                    f"[{timestamp}] batch_error paths=[{joined}] "
                    f"error={exc.__class__.__name__}: {exc}\n"
                )
                log_file.write(error_line)
        except OSError:
            pass

    def _should_ignore_path(self, path: Path) -> bool:
        """Return whether ``path`` should be ignored for watch processing."""

        return self._repository.base_dirname in path.parts

    def _is_within_root(self, path: Path, root: Path) -> bool:
        """Return whether ``path`` resides within ``root``."""

        try:
            path.resolve().relative_to(root.resolve())
            return True
        except (ValueError, FileNotFoundError):
            return False


class _WatchEventHandler(FileSystemEventHandler):
    """Forward filesystem events into the service queue."""

    def __init__(
        self,
        root: Path,
        queue_handle: queue.Queue[tuple[Path | None, WatchEvent | None]],
        state_dirname: str,
    ) -> None:
        self._root = root
        self._queue = queue_handle
        self._state_dirname = state_dirname

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle a filesystem create event."""
        if event.is_directory:
            return
        self._enqueue(kind="created", src_path=event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle a filesystem modify event."""
        if event.is_directory:
            return
        self._enqueue(kind="modified", src_path=event.src_path)

    def on_deleted(self, event: FileSystemEvent) -> None:  # pragma: no cover - watchdog-specific
        """Handle a filesystem delete event."""
        if event.is_directory:
            return
        self._enqueue(kind="deleted", src_path=event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:  # pragma: no cover - watchdog-specific
        """Handle a filesystem move event."""
        if event.is_directory:
            return
        self._enqueue(
            kind="moved", src_path=event.src_path, dest_path=getattr(event, "dest_path", None)
        )

    def _enqueue(
        self,
        *,
        kind: Literal["created", "modified", "deleted", "moved"],
        src_path: str | bytes,
        dest_path: str | bytes | None = None,
    ) -> None:
        """Queue filesystem events for downstream processing."""

        src_str = os.fsdecode(src_path)
        src = Path(src_str).expanduser()
        if self._state_dirname in src.parts:
            return
        src = src.resolve(strict=False)

        dest: Path | None = None
        if dest_path is not None:
            dest_str = os.fsdecode(dest_path)
            candidate = Path(dest_str).expanduser()
            if self._state_dirname in candidate.parts:
                dest = None
            else:
                dest = candidate.resolve(strict=False)

        event = WatchEvent(kind=kind, src=src, dest=dest)
        self._queue.put((self._root, event))
