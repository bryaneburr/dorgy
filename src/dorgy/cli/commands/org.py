"""Organization command implementation for the Dorgy CLI."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click
from rich.table import Table

from dorgy.cli.context import LOGGER, console
from dorgy.cli.helpers.formatting import (
    _descriptor_size,
    _format_size,
    _render_tree,
)
from dorgy.cli.helpers.messages import (
    _collect_llm_metadata,
    _emit_errors,
    _emit_message,
    _format_summary_line,
    _handle_cli_error,
    _llm_summary,
)
from dorgy.cli.helpers.progress import INGESTION_STAGE_LABELS, _ProgressScope, _ProgressTask
from dorgy.cli.helpers.search import _load_embedding_function
from dorgy.cli.lazy import _load_dependency
from dorgy.cli_options import (
    ModeResolution,
    classify_prompt_file_option,
    classify_prompt_option,
    dry_run_option,
    json_option,
    output_option,
    quiet_option,
    recursive_option,
    resolve_mode_settings,
    structure_prompt_file_option,
    structure_prompt_option,
    summary_option,
)
from dorgy.config import ConfigError, ConfigManager
from dorgy.shutdown import ShutdownRequested

if TYPE_CHECKING:
    from dorgy.classification import VisionCache, VisionCaptioner
    from dorgy.ingestion import FileDescriptor
    from dorgy.state import OperationEvent


@click.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@recursive_option("Include all subdirectories.")
@classify_prompt_file_option("Read classification guidance from a text file.")
@classify_prompt_option("Provide extra classification guidance.")
@structure_prompt_file_option("Read extra structure instructions from a file.")
@structure_prompt_option("Provide extra structure instructions.")
@output_option("Directory for organized files.")
@dry_run_option("Preview changes without modifying files.")
@json_option("Emit JSON describing proposed changes.")
@summary_option()
@quiet_option()
@click.option(
    "--with-search",
    is_flag=True,
    help="Build or update the local search index after organization completes.",
)
@click.option(
    "--without-search",
    is_flag=True,
    help="Skip search indexing for this run, overriding config and prior state.",
)
@click.pass_context
def org(
    ctx: click.Context,
    path: str,
    recursive: bool,
    classify_prompt: str | None,
    classify_prompt_file: str | None,
    structure_prompt: str | None,
    structure_prompt_file: str | None,
    output: str | None,
    dry_run: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
    with_search: bool,
    without_search: bool,
) -> None:
    """Organize files rooted at ``PATH`` using the configured ingestion pipeline.

    Args:
        ctx: Click context tracking global mode flags.
        path: Root directory to organize.
        recursive: Whether to include subdirectories during scanning.
        classify_prompt: Inline classification guidance provided via CLI.
        classify_prompt_file: Path to a file containing classification guidance.
        structure_prompt: Inline structure guidance provided via CLI.
        structure_prompt_file: Path to a structure guidance file.
        output: Optional destination root for organized files.
        dry_run: Indicates whether to preview changes without mutating files.
        json_output: Indicates whether JSON output mode is active.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.
        with_search: Forces search indexing after organization.
        without_search: Skips search indexing regardless of configuration.

    Raises:
        click.ClickException: When validation fails before executing the pipeline.
    """

    from dorgy.cli_support import (
        build_original_snapshot,
        collect_error_payload,
        compute_org_counts,
        descriptor_to_record,
        relative_to_collection,
        resolve_prompt_text,
        run_classification,
        zip_decisions,
    )

    ClassificationCacheCls = _load_dependency(
        "ClassificationCache", "dorgy.classification", "ClassificationCache"
    )
    VisionCacheCls = _load_dependency("VisionCache", "dorgy.classification", "VisionCache")
    VisionCaptionerCls = _load_dependency(
        "VisionCaptioner", "dorgy.classification", "VisionCaptioner"
    )
    StructurePlannerCls = _load_dependency(
        "StructurePlanner", "dorgy.classification.structure", "StructurePlanner"
    )
    LLMUnavailableError = _load_dependency(
        "LLMUnavailableError", "dorgy.classification.exceptions", "LLMUnavailableError"
    )
    LLMResponseError = _load_dependency(
        "LLMResponseError", "dorgy.classification.exceptions", "LLMResponseError"
    )
    IngestionPipelineCls = _load_dependency(
        "IngestionPipeline", "dorgy.ingestion", "IngestionPipeline"
    )
    HashComputerCls = _load_dependency("HashComputer", "dorgy.ingestion.detectors", "HashComputer")
    TypeDetectorCls = _load_dependency("TypeDetector", "dorgy.ingestion.detectors", "TypeDetector")
    DirectoryScannerCls = _load_dependency(
        "DirectoryScanner", "dorgy.ingestion.discovery", "DirectoryScanner"
    )
    MetadataExtractorCls = _load_dependency(
        "MetadataExtractor", "dorgy.ingestion.extractors", "MetadataExtractor"
    )
    OperationExecutorCls = _load_dependency(
        "OperationExecutor", "dorgy.organization.executor", "OperationExecutor"
    )
    OrganizerPlannerCls = _load_dependency(
        "OrganizerPlanner", "dorgy.organization.planner", "OrganizerPlanner"
    )
    CollectionStateCls = _load_dependency("CollectionState", "dorgy.state", "CollectionState")
    StateRepositoryCls = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")
    SearchEntryCls = _load_dependency("SearchEntry", "dorgy.search", "SearchEntry")
    SearchIndexError = _load_dependency("SearchIndexError", "dorgy.search", "SearchIndexError")
    ensure_search_index = _load_dependency("ensure_index", "dorgy.search.lifecycle", "ensure_index")
    update_search_entries = _load_dependency(
        "update_entries", "dorgy.search.lifecycle", "update_entries"
    )
    descriptor_document_text = _load_dependency(
        "descriptor_document_text", "dorgy.search.text", "descriptor_document_text"
    )

    json_enabled = json_output
    mode: ModeResolution | None = None
    try:
        classification_prompt = resolve_prompt_text(classify_prompt, classify_prompt_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(
            f"Failed to read classification prompt file {classify_prompt_file}: {exc}"
        ) from exc
    try:
        structure_prompt_value = resolve_prompt_text(structure_prompt, structure_prompt_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(
            f"Failed to read structure prompt file {structure_prompt_file}: {exc}"
        ) from exc
    if structure_prompt_value is None:
        structure_prompt_value = classification_prompt
    if with_search and without_search:
        raise click.ClickException("--with-search cannot be combined with --without-search.")
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        mode = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        if mode is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Failed to resolve mode settings")
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output
        progress_enabled = (
            config.cli.progress_enabled
            and console.is_terminal
            and not json_enabled
            and not quiet_enabled
            and not summary_only
        )

        source_root = Path(path).expanduser().resolve()
        target_root = source_root
        copy_mode = False
        if output:
            target_root = Path(output).expanduser().resolve()
            if not dry_run:
                target_root.mkdir(parents=True, exist_ok=True)
            copy_mode = target_root != source_root

        recursive = recursive or config.processing.recurse_directories
        include_hidden = config.processing.process_hidden_files
        follow_symlinks = config.processing.follow_symlinks
        max_size_bytes = None
        if config.processing.max_file_size_mb > 0:
            max_size_bytes = config.processing.max_file_size_mb * 1024 * 1024

        scanner = DirectoryScannerCls(
            recursive=recursive,
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
            max_size_bytes=max_size_bytes,
        )
        state_dir = target_root / ".dorgy"
        staging_dir = None if dry_run else state_dir / "staging"
        classification_cache = ClassificationCacheCls(state_dir / "classifications.json")
        vision_captioner: "VisionCaptioner | None" = None
        vision_warning: str | None = None
        if config.processing.process_images:
            cache_instance = cast("VisionCache", VisionCacheCls(state_dir / "vision.json"))
            cache_instance.load()
            try:
                vision_captioner = cast(
                    "VisionCaptioner",
                    VisionCaptionerCls(config.llm, cache=cache_instance),
                )
            except RuntimeError as exc:
                vision_warning = f"Vision captioning disabled: {exc}"
                LOGGER.warning("%s", vision_warning)
                vision_captioner = None

        pipeline = IngestionPipelineCls(
            scanner=scanner,
            detector=TypeDetectorCls(),
            hasher=HashComputerCls(),
            extractor=MetadataExtractorCls(preview_char_limit=config.processing.preview_char_limit),
            processing=config.processing,
            staging_dir=staging_dir,
            allow_writes=not dry_run,
            vision_captioner=vision_captioner,
        )

        planner = OrganizerPlannerCls()
        parallel_workers = max(1, config.processing.parallel_workers)

        with _ProgressScope(progress_enabled) as progress:
            ingestion_task = progress.start("Preparing files")
            ingestion_state = {"completed": 0}
            ingestion_worker_tasks: dict[int, _ProgressTask] = {}

            def _ingestion_stage(
                stage: str,
                stage_path: Path,
                info: dict[str, Any] | None,
            ) -> None:
                label = INGESTION_STAGE_LABELS.get(stage, stage.replace("_", " ").title())
                completed = ingestion_state["completed"]
                path_name = stage_path.name
                size_value = None
                if info is not None and "size_bytes" in info:
                    try:
                        size_value = int(info["size_bytes"])
                    except (TypeError, ValueError):
                        size_value = None
                size_suffix = f" ({_format_size(size_value)})" if size_value is not None else ""
                worker_id: int | None = None
                if info is not None and "worker_id" in info:
                    try:
                        worker_id = int(info["worker_id"])
                    except (TypeError, ValueError):
                        worker_id = None

                def _ensure_worker_task(identifier: int) -> _ProgressTask:
                    task = ingestion_worker_tasks.get(identifier)
                    if task is None:
                        task = progress.start("", total=None)
                        ingestion_worker_tasks[identifier] = task
                    return task

                if worker_id is not None and progress_enabled:
                    task = _ensure_worker_task(worker_id)
                    if stage in {"complete", "error", "skipped", "quarantine"}:
                        task.complete("")
                        ingestion_worker_tasks.pop(worker_id, None)
                    else:
                        task.update(f"{path_name}{size_suffix} – {label.lower()}")
                    return

                if stage == "complete":
                    ingestion_state["completed"] += 1
                    updated = ingestion_state["completed"]
                    ingestion_task.update(f"Completed ({updated}) {path_name}{size_suffix}")
                elif stage == "error":
                    ingestion_task.update(f"Error: {path_name}{size_suffix}")
                elif stage == "skipped":
                    ingestion_task.update(f"Skipped {path_name}{size_suffix} ({completed} done)")
                elif stage == "quarantine":
                    ingestion_task.update(
                        f"Quarantined {path_name}{size_suffix} ({completed} done)"
                    )
                else:
                    ingestion_task.update(f"{label}: {path_name}{size_suffix} ({completed} done)")

            result = pipeline.run(
                [source_root],
                on_stage=_ingestion_stage if progress_enabled else None,
                prompt=classification_prompt,
            )
            if not dry_run and vision_captioner is not None:
                vision_captioner.save_cache()
            files_total = len(result.processed)
            ingestion_task.complete(f"Ingestion complete ({files_total} file(s))")

            overall_task: _ProgressTask | None = None
            worker_tasks: dict[int, _ProgressTask] = {}

            if files_total > 0:
                overall_task = progress.start(
                    "Classifying files",
                    total=files_total,
                )

            def _classification_progress(
                event: str,
                processed: int,
                total: int,
                descriptor: FileDescriptor,
                worker_id: int | None,
                duration: float | None,
            ) -> None:
                if overall_task is None:
                    return

                name = descriptor.path.name
                size_text = _format_size(_descriptor_size(descriptor))
                display = f"{name} ({size_text})" if size_text != "?" else name

                if event == "start":
                    if worker_id is None:
                        overall_task.update(f"Classifying cached ({processed}/{total}) {display}")
                        return
                    task = worker_tasks.get(worker_id)
                    if task is None:
                        task = progress.start("", total=None)
                        worker_tasks[worker_id] = task
                    task.update(display)
                    return

                if event == "complete":
                    overall_task.update(f"Classified {processed}/{total}")
                    overall_task.advance()
                    if worker_id is not None:
                        task = worker_tasks.get(worker_id)
                        if task is not None:
                            task.complete("")
                            worker_tasks.pop(worker_id, None)
                    return

            classification_batch = run_classification(
                result.processed,
                classification_prompt=classification_prompt,
                root=source_root,
                dry_run=dry_run,
                config=config,
                cache=classification_cache,
                on_progress=(
                    _classification_progress if progress_enabled and files_total else None
                ),
                max_workers=parallel_workers,
            )
            if overall_task is not None:
                overall_task.complete("Classification complete")

            paired = list(zip_decisions(classification_batch, result.processed))
            descriptor_list = [descriptor for _, descriptor in paired]
            decision_list = [decision for decision, _ in paired]
            confidence_threshold = config.ambiguity.confidence_threshold
            for decision, descriptor in paired:
                if decision is not None and decision.confidence < confidence_threshold:
                    decision.needs_review = True
                    if descriptor.path not in result.needs_review:
                        result.needs_review.append(descriptor.path)

            structure_map: dict[Path, Path] = {}
            structure_task: _ProgressTask | None = None
            if descriptor_list and progress_enabled:
                structure_task = progress.start(
                    f"Planning structure ({len(descriptor_list)} files)",
                    total=None,
                )
            if descriptor_list:
                try:
                    structure_planner = StructurePlannerCls(config.llm)
                    structure_map = structure_planner.propose(
                        descriptor_list,
                        decision_list,
                        source_root=source_root,
                        prompt=structure_prompt_value,
                    )
                    if structure_task is not None:
                        structure_task.complete("Structure plan ready")
                except LLMUnavailableError:
                    if structure_task is not None:
                        structure_task.complete("Structure plan skipped")
                    raise
                except LLMResponseError:
                    if structure_task is not None:
                        structure_task.complete("Structure plan failed")
                    raise
                except Exception as exc:  # pragma: no cover - best-effort hint
                    if structure_task is not None:
                        structure_task.complete("Structure plan skipped")
                    LOGGER.debug("Structure planner unavailable: %s", exc)
            elif structure_task is not None:
                structure_task.complete("Structure plan skipped")

            plan_task = progress.start("Building operation plan")
            plan = planner.build_plan(
                descriptors=descriptor_list,
                decisions=decision_list,
                rename_enabled=config.organization.rename_files,
                root=target_root,
                conflict_strategy=config.organization.conflict_resolution,
                destination_map=structure_map,
            )
            plan_task.complete("Operation plan ready")
            if vision_warning:
                plan.notes.append(vision_warning)
        rename_map = {operation.source: operation.destination for operation in plan.renames}
        move_map = {operation.source: operation.destination for operation in plan.moves}

        final_path_map: dict[Path, Path] = {}
        file_entries: list[dict[str, Any]] = []
        table_rows: list[tuple[str, str, str, str, str, str]] = []

        for decision, descriptor in paired:
            original_path = descriptor.path
            rename_target = rename_map.get(original_path)
            move_key = rename_target if rename_target is not None else original_path
            move_target = move_map.get(move_key)
            final_path = move_target or rename_target or original_path
            final_path_map[original_path] = final_path

            vision_metadata: dict[str, Any] | None = None
            if config.processing.process_images and descriptor.metadata.get("vision_caption"):
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
                    "classification": decision.model_dump(mode="json")
                    if decision is not None
                    else None,
                    "vision": vision_metadata,
                    "operations": {
                        "rename": rename_target.as_posix() if rename_target is not None else None,
                        "move": move_target.as_posix() if move_target is not None else None,
                    },
                }
            )

            metadata = descriptor.metadata
            relative_path = original_path
            try:
                relative_path = original_path.relative_to(source_root)
            except ValueError:
                pass
            category = decision.primary_category if decision else "-"
            confidence_value = "-"
            status_label = "-"
            if decision is not None:
                if decision.confidence is not None:
                    confidence_value = f"{decision.confidence:.2f}"
                status_label = "Review" if decision.needs_review else "Ok"
            table_rows.append(
                (
                    str(relative_path),
                    descriptor.mime_type,
                    str(metadata.get("size_bytes", "?")),
                    category,
                    confidence_value,
                    status_label,
                )
            )

        llm_metadata = _collect_llm_metadata(config.llm)
        counts = compute_org_counts(result, classification_batch, plan)
        json_payload: dict[str, Any] = {
            "context": {
                "source_root": source_root.as_posix(),
                "destination_root": target_root.as_posix(),
                "copy_mode": copy_mode,
                "dry_run": dry_run,
                "classification_prompt": classification_prompt,
                "structure_prompt": structure_prompt_value,
                # Backwards compatibility: retain legacy key.
                "prompt": classification_prompt,
            },
            "counts": counts,
            "plan": plan.model_dump(mode="json"),
            "files": file_entries,
            "notes": list(plan.notes),
        }
        json_payload["context"]["llm"] = llm_metadata
        json_payload["errors"] = collect_error_payload(result, classification_batch)

        if json_output and dry_run:
            console.print_json(data=json_payload)
            return

        if not json_output:
            table_title = (
                f"Organization preview for {source_root}"
                if not copy_mode
                else f"Organization preview for {source_root} → {target_root}"
            )
            table = Table(title=table_title)
            table.add_column("File", overflow="fold")
            table.add_column("Type")
            table.add_column("Size", justify="right")
            threshold = config.ambiguity.confidence_threshold
            table.add_column("Category")
            table.add_column(f"Confidence ≥ {threshold:.2f}", justify="right")
            table.add_column("Status", justify="center")
            for row in table_rows:
                table.add_row(*row)
            _emit_message(table, mode="detail", quiet=quiet_enabled, summary_only=summary_only)

            llm_summary_text = _llm_summary(llm_metadata)
            _emit_message(
                f"[cyan]LLM configuration: {llm_summary_text}[/cyan]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

            tree_output = _render_tree(final_path_map.values(), target_root)
            if tree_output:
                tree_mode = "summary" if summary_only else "detail"
                _emit_message(
                    f"[cyan]Proposed file tree for {target_root}:[/cyan]",
                    mode=tree_mode,
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for line in tree_output.splitlines():
                    _emit_message(
                        f"  {line}",
                        mode=tree_mode,
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )

            classification_total = sum(
                1 for decision in classification_batch.decisions if decision is not None
            )
            review_count = sum(
                1
                for decision in classification_batch.decisions
                if decision is not None and decision.needs_review
            )
            if classification_total:
                _emit_message(
                    f"[cyan]Classification evaluated {classification_total} file(s); "
                    f"{review_count} marked for review.[/cyan]",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if result.needs_review:
                _emit_message(
                    f"[yellow]{len(result.needs_review)} files require review based on the current "
                    "confidence threshold.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if result.quarantined:
                _emit_message(
                    f"[yellow]{len(result.quarantined)} files would be quarantined during "
                    "execution.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if plan.metadata_updates:
                _emit_message(
                    f"[cyan]{len(plan.metadata_updates)} metadata update(s) planned.[/cyan]",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if plan.notes:
                _emit_message(
                    "[yellow]Plan notes:[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for note in plan.notes:
                    _emit_message(
                        f"  - {note}",
                        mode="warning",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )

        if dry_run:
            if not json_output:
                _emit_errors(
                    json_payload["errors"],
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                summary_metrics = {
                    "dry_run": True,
                    "processed": counts["processed"],
                    "needs_review": counts["needs_review"],
                    "quarantined": counts["quarantined"],
                    "renames": counts["renames"],
                    "moves": counts["moves"],
                    "conflicts": counts["conflicts"],
                    "errors": counts["errors"],
                }
                _emit_message(
                    _format_summary_line("Organization", target_root, summary_metrics),
                    mode="summary",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                _emit_message(
                    "[yellow]Dry run selected; skipping state persistence.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
            return

        repository = StateRepositoryCls()
        state_dir = repository.initialize(target_root)
        quarantine_dir = state_dir / "quarantine"
        if result.quarantined and config.processing.corrupted_files.action == "quarantine":
            moved_paths: list[Path] = []
            for original in result.quarantined:
                target = quarantine_dir / original.name
                counter = 1
                while target.exists():
                    target = target.with_name(f"{original.stem}-{counter}{original.suffix}")
                    counter += 1
                try:
                    shutil.move(str(original), str(target))
                except Exception as exc:  # pragma: no cover - filesystem issues
                    _emit_message(
                        f"[red]Failed to quarantine {original}: {exc}[/red]",
                        mode="error",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )
                    result.errors.append(f"{original}: quarantine failed ({exc})")
                else:
                    moved_paths.append(target)
            result.quarantined = moved_paths
            if moved_paths:
                _emit_message(
                    f"[yellow]Moved {len(moved_paths)} files to quarantine.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
        try:
            state = repository.load(target_root)
        except MissingStateError:
            state = CollectionStateCls(root=str(target_root))
        search_enabled = state.search.enabled
        if with_search:
            search_enabled = True
        elif without_search:
            search_enabled = False
        elif not search_enabled and config.search.auto_enable_org:
            search_enabled = True

        snapshot: dict[str, Any] | None = None
        if not dry_run:
            snapshot = build_original_snapshot(
                [descriptor for _, descriptor in paired], source_root
            )

        executor = OperationExecutorCls(
            staging_root=state_dir / "staging",
            copy_mode=copy_mode,
            source_root=source_root,
        )
        events: list[OperationEvent] = []
        try:
            if snapshot is not None:
                repository.write_original_structure(target_root, snapshot)
            with _ProgressScope(progress_enabled) as progress:
                apply_task = progress.start("Applying operation plan")
                events = executor.apply(plan, target_root)
                apply_task.complete("Operation plan applied")
        except Exception as exc:
            raise click.ClickException(
                f"Failed to apply organization plan: {exc}. "
                "Verify file permissions and available disk space."
            ) from exc

        for decision, descriptor in paired:
            original_path = descriptor.path
            final_path = final_path_map.get(original_path, original_path)
            old_relative = relative_to_collection(original_path, target_root)

            descriptor.path = final_path
            descriptor.display_name = descriptor.path.name

            record = descriptor_to_record(descriptor, decision, target_root)

            previous_record = state.files.pop(old_relative, None)
            if previous_record is not None:
                record.document_id = previous_record.document_id
            state.files[record.path] = record

        state.search.enabled = search_enabled
        if not search_enabled:
            state.search.last_indexed_at = None
        if search_enabled:
            try:
                embedding_function = _load_embedding_function(config.search.embedding_function)
                search_index = ensure_search_index(
                    target_root, state, embedding_function=embedding_function
                )
                search_entries: list[Any] = []
                for _, descriptor in paired:
                    document_text = descriptor_document_text(descriptor)
                    if not document_text:
                        continue
                    final_relative = relative_to_collection(descriptor.path, target_root)
                    record = state.files.get(final_relative)
                    if record is None:
                        continue
                    entry = SearchEntryCls.from_record(
                        record,
                        document_text,
                        extra_metadata={"mime_type": descriptor.mime_type, "source": "org"},
                    )
                    search_entries.append(entry)
                update_search_entries(search_index, state, search_entries)
                if search_entries and not json_output:
                    _emit_message(
                        f"[cyan]Indexed {len(search_entries)} document(s) for search.[/cyan]",
                        mode="detail",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )
            except SearchIndexError as exc:
                state.search.enabled = False
                _emit_message(
                    f"[yellow]Search indexing skipped: {exc}[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        repository.save(target_root, state)
        if events:
            repository.append_history(target_root, events)

        if not json_output:
            _emit_message(
                f"[green]Persisted state for {len(result.processed)} files.[/green]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            if copy_mode:
                _emit_message(
                    f"[cyan]Copy mode enabled; organized files written to {target_root} while "
                    f"preserving originals at {source_root}.[/cyan]",
                    mode="summary",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        log_path = state_dir / "dorgy.log"
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                timestamp = datetime.now(timezone.utc).isoformat()
                log_file.write(
                    f"[{timestamp}] processed={len(result.processed)} "
                    f"needs_review={len(result.needs_review)} "
                    f"quarantined={len(result.quarantined)} "
                    f"classification={len(classification_batch.decisions)} "
                    f"classification_errors={len(classification_batch.errors)} "
                    f"renames={len(plan.renames)} moves={len(plan.moves)} "
                    f"errors={len(result.errors)}\n"
                )
                for error in result.errors:
                    log_file.write(f"  error: {error}\n")
                for error in classification_batch.errors:
                    log_file.write(f"  classification_error: {error}\n")
                for q_path in result.quarantined:
                    log_file.write(f"  quarantined: {q_path}\n")
                for rename_op in plan.renames:
                    log_file.write(f"  rename: {rename_op.source} -> {rename_op.destination}\n")
                for move_op in plan.moves:
                    log_file.write(f"  move: {move_op.source} -> {move_op.destination}\n")
        except OSError as exc:  # pragma: no cover - logging best effort
            _emit_message(
                f"[yellow]Unable to update log file: {exc}[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        counts = compute_org_counts(result, classification_batch, plan)
        errors_payload = collect_error_payload(result, classification_batch)
        json_payload["counts"] = counts
        json_payload["errors"] = errors_payload
        json_payload["history"] = [event.model_dump(mode="json") for event in events]
        json_payload["state"] = {
            "path": str(state_dir / "state.json"),
            "files_tracked": len(state.files),
        }
        json_payload["log_path"] = str(log_path)
        json_payload["quarantine"] = [path.as_posix() for path in result.quarantined]
        json_payload["context"]["state_dir"] = state_dir.as_posix()

        if not json_output:
            _emit_errors(errors_payload, quiet=quiet_enabled, summary_only=summary_only)
            summary_metrics = {
                "processed": counts["processed"],
                "needs_review": counts["needs_review"],
                "quarantined": counts["quarantined"],
                "renames": counts["renames"],
                "moves": counts["moves"],
                "conflicts": counts["conflicts"],
                "errors": counts["errors"],
            }
            _emit_message(
                _format_summary_line("Organization", target_root, summary_metrics),
                mode="summary",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
        else:
            console.print_json(data=json_payload)
    except ShutdownRequested:
        quiet_flag = mode.quiet if mode is not None else quiet
        summary_flag = mode.summary if mode is not None else summary_mode
        if not json_enabled:
            _emit_message(
                "[yellow]Organization cancelled by user request.[/yellow]",
                mode="summary",
                quiet=quiet_flag,
                summary_only=summary_flag,
            )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except LLMUnavailableError as exc:
        _handle_cli_error(
            str(exc),
            code="llm_unavailable",
            json_output=json_enabled,
            original=exc,
        )
    except LLMResponseError as exc:
        _handle_cli_error(
            str(exc),
            code="llm_response_error",
            json_output=json_enabled,
            original=exc,
        )
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while organizing files: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


def register_org_command(cli: click.Group) -> None:
    """Register the organization command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(org)


__all__ = ["org", "register_org_command"]
