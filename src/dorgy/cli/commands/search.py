"""Search command implementation for the Dorgy CLI."""

from __future__ import annotations

import fnmatch
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from rich.table import Table

from dorgy.cli.context import LOGGER, console
from dorgy.cli.helpers.formatting import _format_modified_timestamp
from dorgy.cli.helpers.messages import _emit_message, _format_summary_line, _handle_cli_error
from dorgy.cli.helpers.options import (
    ModeResolution,
    json_option,
    quiet_option,
    resolve_mode_settings,
    summary_option,
)
from dorgy.cli.helpers.parsing import _parse_csv_option, _parse_datetime_option
from dorgy.cli.helpers.search import _load_embedding_function
from dorgy.cli.helpers.state import _normalise_state_key, relative_to_collection
from dorgy.cli.lazy import _load_dependency
from dorgy.config import ConfigError, ConfigManager

if TYPE_CHECKING:
    from dorgy.state import FileRecord


@click.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option(
    "--search",
    "query",
    type=str,
    help="Free-text search across paths, tags, and categories.",
)
@click.option("--name", type=str, help="Filename glob filter (e.g., '*.pdf').")
@click.option(
    "--tags",
    type=str,
    help="Comma-separated tag filters (matches all provided tags).",
)
@click.option(
    "--categories",
    type=str,
    help="Comma-separated category filters (matches all provided categories).",
)
@click.option(
    "--before",
    type=str,
    help="Return results with modified time before this ISO 8601 timestamp.",
)
@click.option(
    "--after",
    type=str,
    help="Return results with modified time on or after this ISO 8601 timestamp.",
)
@click.option(
    "--needs-review/--any-review",
    "needs_review",
    default=None,
    help="Filter results by needs-review flag (default is to include all).",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    show_default=False,
    help="Maximum number of results to return (defaults to configuration).",
)
@click.option("--contains", type=str, help="Substring filter for document contents.")
@click.option("--init-store", is_flag=True, help="Rebuild the Chromadb store from disk.")
@click.option("--drop-store", is_flag=True, help="Delete the Chromadb store and disable search.")
@click.option(
    "--reindex",
    is_flag=True,
    help="Drop and rebuild the Chromadb store for the collection.",
)
@json_option("Emit search results as JSON.")
@summary_option()
@quiet_option()
@click.pass_context
def search(
    ctx: click.Context,
    path: str,
    query: str | None,
    name: str | None,
    tags: str | None,
    categories: str | None,
    before: str | None,
    after: str | None,
    needs_review: bool | None,
    limit: int | None,
    contains: str | None,
    init_store: bool,
    drop_store: bool,
    reindex: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Search within an organized collection's state metadata.

    Args:
        ctx: Click context tracking global mode flags.
        path: Collection root to search.
        query: Free-text query string.
        name: Filename glob pattern filter.
        tags: Comma-separated tag filter string.
        categories: Comma-separated category filter string.
        before: Upper bound on modification timestamp.
        after: Lower bound on modification timestamp.
        needs_review: Optional needs-review filter flag.
        limit: Maximum number of results to display.
        contains: Substring filter for document contents.
        init_store: Whether to rebuild the search store from disk before querying.
        drop_store: Whether to drop the search store and disable search.
        reindex: Whether to rebuild the search store from scratch.
        json_output: Indicates whether JSON output mode is active.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.

    Raises:
        click.ClickException: When validation fails before performing the search.
    """

    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")
    SearchIndexError = _load_dependency("SearchIndexError", "dorgy.search", "SearchIndexError")

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        if init_store and drop_store:
            raise click.ClickException("--init-store cannot be combined with --drop-store.")
        if reindex and drop_store:
            raise click.ClickException("--reindex cannot be combined with --drop-store.")
        if reindex and init_store:
            raise click.ClickException("--reindex cannot be combined with --init-store.")
        if query and contains:
            raise click.ClickException("--search cannot be combined with --contains.")

        mode: ModeResolution = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output

        default_limit = config.search.default_limit
        legacy_limit = config.cli.search_default_limit
        if legacy_limit is not None:
            default_limit = legacy_limit
        effective_limit = limit if limit is not None else default_limit
        if effective_limit is not None and effective_limit <= 0:
            raise click.ClickException("--limit must be greater than zero.")

        before_dt = _parse_datetime_option("--before", before)
        after_dt = _parse_datetime_option("--after", after)
        if before_dt and after_dt and after_dt > before_dt:
            raise click.ClickException("--after must be earlier than or equal to --before.")

        tag_terms = _parse_csv_option(tags)
        category_terms = _parse_csv_option(categories)
        tag_filters = {value.lower() for value in tag_terms}
        category_filters = {value.lower() for value in category_terms}
        query_text = query.lower().strip() if query else None
        name_pattern = name.strip() if name else None

        root = Path(path).expanduser().resolve()
        repository = StateRepository()
        state = repository.load(root)

        search_state = getattr(state, "search", None)
        search_enabled = bool(search_state.enabled) if search_state is not None else False

        if not search_enabled and not (init_store or reindex):
            raise click.ClickException(
                "Search index is disabled for this collection. "
                "Run `dorgy search --init-store` or `dorgy org --with-search` first."
            )

        records_by_normalized: dict[str, FileRecord] = {}
        records_by_document_id: dict[str, FileRecord] = {}
        for key, record in state.files.items():
            normalized_key = _normalise_state_key(key)
            records_by_normalized[normalized_key] = record
            records_by_document_id[record.document_id] = record

        search_notes: list[str] = []
        search_warnings: list[str] = []
        snippet_by_id: dict[str, str] = {}
        score_by_id: dict[str, float | None] = {}
        distance_by_id: dict[str, float | None] = {}
        space_by_id: dict[str, str | None] = {}
        search_status: dict[str, Any] | None = None
        embedding_function = _load_embedding_function(config.search.embedding_function)
        search_index: Any | None = None

        if drop_store:
            drop_search_index = _load_dependency(
                "drop_index", "dorgy.search.lifecycle", "drop_index"
            )
            drop_search_index(root, state)
            repository.save(root, state)
            search_notes.append("Search index dropped; state marked as search-disabled.")
            search_enabled = False

        if reindex:
            SearchIndexCls = _load_dependency("SearchIndex", "dorgy.search", "SearchIndex")
            existing_index = SearchIndexCls(root, embedding_function=embedding_function)
            if existing_index.index_path.exists():
                doc_ids = [record.document_id for record in state.files.values()]
                try:
                    existing_index.delete(doc_ids)
                    search_notes.append(
                        f"Cleared {len(doc_ids)} document(s) before reindex."
                        if doc_ids
                        else "Cleared existing search index before reindex."
                    )
                except SearchIndexError as exc:
                    search_warnings.append(f"Unable to clear existing index before reindex: {exc}")
            init_store = True

        if init_store:
            SearchEntryCls = _load_dependency("SearchEntry", "dorgy.search", "SearchEntry")
            ensure_search_index = _load_dependency(
                "ensure_index", "dorgy.search.lifecycle", "ensure_index"
            )
            update_search_entries = _load_dependency(
                "update_entries", "dorgy.search.lifecycle", "update_entries"
            )
            descriptor_document_text = _load_dependency(
                "descriptor_document_text", "dorgy.search.text", "descriptor_document_text"
            )
            DirectoryScannerCls = _load_dependency(
                "DirectoryScanner", "dorgy.ingestion.discovery", "DirectoryScanner"
            )
            TypeDetectorCls = _load_dependency(
                "TypeDetector", "dorgy.ingestion.detectors", "TypeDetector"
            )
            HashComputerCls = _load_dependency(
                "HashComputer", "dorgy.ingestion.detectors", "HashComputer"
            )
            MetadataExtractorCls = _load_dependency(
                "MetadataExtractor", "dorgy.ingestion.extractors", "MetadataExtractor"
            )
            IngestionPipelineCls = _load_dependency(
                "IngestionPipeline", "dorgy.ingestion", "IngestionPipeline"
            )
            VisionCaptionerCls = _load_dependency(
                "VisionCaptioner", "dorgy.classification", "VisionCaptioner"
            )
            VisionCacheCls = _load_dependency("VisionCache", "dorgy.classification", "VisionCache")

            search_index = ensure_search_index(root, state, embedding_function=embedding_function)
            search_enabled = True

            vision_captioner: Any | None = None
            vision_warning: str | None = None
            vision_cache: Any | None = None
            state_dir = root / ".dorgy"
            if config.processing.process_images:
                vision_cache = VisionCacheCls(state_dir / "vision.json")
                try:
                    vision_cache.load()
                except OSError as exc:
                    search_warnings.append(f"Unable to load vision cache: {exc}")
                try:
                    vision_captioner = VisionCaptionerCls(config.llm, cache=vision_cache)
                except RuntimeError as exc:
                    vision_warning = f"Vision captioning disabled: {exc}"
                    LOGGER.warning("%s", vision_warning)
                    vision_captioner = None
            if vision_warning:
                search_warnings.append(vision_warning)

            max_size_bytes = None
            if config.processing.max_file_size_mb > 0:
                max_size_bytes = config.processing.max_file_size_mb * 1024 * 1024

            scanner = DirectoryScannerCls(
                recursive=True,
                include_hidden=config.processing.process_hidden_files,
                follow_symlinks=config.processing.follow_symlinks,
                max_size_bytes=max_size_bytes,
            )
            extractor = MetadataExtractorCls(
                preview_char_limit=config.processing.preview_char_limit
            )
            pipeline = IngestionPipelineCls(
                scanner=scanner,
                detector=TypeDetectorCls(),
                hasher=HashComputerCls(),
                extractor=extractor,
                processing=config.processing,
                staging_dir=None,
                allow_writes=False,
                vision_captioner=vision_captioner,
            )

            ingestion_result = pipeline.run([root])
            if vision_captioner is not None:
                try:
                    vision_captioner.save_cache()
                except OSError as exc:
                    search_warnings.append(f"Unable to persist vision cache: {exc}")

            search_entries: list[Any] = []
            skipped_previews = 0
            for descriptor in ingestion_result.processed:
                relative = relative_to_collection(descriptor.path, root)
                normalized = _normalise_state_key(relative)
                record = records_by_normalized.get(normalized)
                if record is None:
                    continue
                document_text = descriptor_document_text(descriptor)
                if not document_text:
                    skipped_previews += 1
                    continue
                entry = SearchEntryCls.from_record(
                    record,
                    document_text,
                    extra_metadata={
                        "mime_type": descriptor.mime_type,
                        "source": "search-init",
                    },
                )
                search_entries.append(entry)

            if search_entries:
                update_search_entries(search_index, state, search_entries)
                repository.save(root, state)
                if reindex:
                    search_notes.append(
                        f"Reindexed {len(search_entries)} document(s) via --reindex."
                    )
                else:
                    search_notes.append(
                        f"Indexed {len(search_entries)} document(s) via --init-store."
                    )
            else:
                if reindex:
                    search_notes.append("No search entries generated during --reindex.")
                else:
                    search_notes.append("No search entries generated during --init-store.")

            if skipped_previews:
                search_warnings.append(
                    f"{skipped_previews} file(s) lacked preview content during index rebuild."
                )

        if search_index is None and state.search.enabled:
            SearchIndexCls = _load_dependency("SearchIndex", "dorgy.search", "SearchIndex")
            candidate_index = SearchIndexCls(root, embedding_function=embedding_function)
            if candidate_index.index_path.exists():
                search_index = candidate_index
            else:
                warning_text = (
                    "Search metadata indicates the index is enabled, "
                    "but Chromadb artifacts were not found. "
                    "Rebuild the index with `dorgy search --init-store`."
                )
                if contains:
                    raise click.ClickException(
                        "Substring filtering requires an existing Chromadb index. "
                        "Run `dorgy search --init-store` or `dorgy org --with-search` "
                        "to create one."
                    )
                search_warnings.append(warning_text)

        if search_index is None and not drop_store:
            candidate_index = _load_dependency("SearchIndex", "dorgy.search", "SearchIndex")(
                root, embedding_function=embedding_function
            )
            if not candidate_index.index_path.exists():
                raise click.ClickException(
                    "Search index has not been initialised for this collection. "
                    "Run `dorgy search --init-store` or `dorgy org --with-search` first."
                )
            search_index = candidate_index

        if search_index is not None:
            search_status = search_index.status()

        semantic_mode = query is not None and query.strip() != ""

        if drop_store and (semantic_mode or contains):
            raise click.ClickException(
                "--drop-store cannot be combined with --search or --contains."
            )
        candidate_ids: set[str] | None = None
        candidate_order: dict[str, int] = {}

        if semantic_mode:
            if search_index is None:
                raise click.ClickException(
                    "Semantic search requires an existing Chromadb index. "
                    "Run `dorgy search --init-store` or `dorgy org --with-search` to create one."
                )
            semantic_limit = effective_limit or len(state.files) or 0
            if semantic_limit <= 0:
                semantic_limit = len(state.files)
            semantic_limit = min(len(state.files) or semantic_limit, semantic_limit)
            try:
                response = search_index.query(
                    query,
                    limit=semantic_limit or None,
                    include_documents=True,
                )
            except SearchIndexError as exc:
                raise click.ClickException(
                    "Semantic search is unavailable because the collection's vector index "
                    "is not initialised. Rebuild it with `dorgy search --init-store` or "
                    "`dorgy org --with-search`. "
                    f"Details: {exc}"
                ) from exc
            ids_matrix = response.get("ids", [[]])
            distances_matrix = response.get("distances", [[]])
            documents_matrix = (
                response.get("documents", [[]]) if response.get("documents") else [[]]
            )
            ids = ids_matrix[0] if ids_matrix else []
            distances = distances_matrix[0] if distances_matrix else []
            documents = documents_matrix[0] if documents_matrix else []
            candidate_ids = set()
            for idx, doc_id in enumerate(ids):
                record = records_by_document_id.get(doc_id)
                if record is None:
                    continue
                candidate_order[doc_id] = len(candidate_order)
                candidate_ids.add(doc_id)
                distance = distances[idx] if idx < len(distances) else None
                if isinstance(distance, (int, float)):
                    score = 1.0 - float(distance)
                    score_by_id[doc_id] = max(0.0, min(1.0, score))
                    distance_by_id[doc_id] = float(distance)
                else:
                    score_by_id[doc_id] = None
                    distance_by_id[doc_id] = None
                if search_status and isinstance(search_status.get("space"), str):
                    space_by_id[doc_id] = str(search_status["space"])
                else:
                    space_by_id[doc_id] = space_by_id.get(doc_id) or "cosine"
                documents_value = documents[idx] if idx < len(documents) else ""
                if documents_value:
                    snippet_by_id[doc_id] = documents_value

        if contains:
            if search_index is None:
                raise click.ClickException(
                    "Substring filtering requires an existing Chromadb index. "
                    "Run `dorgy search --init-store` or `dorgy org --with-search` to create one."
                )
            response = search_index.contains(
                contains,
                limit=effective_limit,
                include_documents=True,
            )
            ids = response.get("ids", []) or []
            documents = response.get("documents", []) or []
            candidate_ids = set(ids)
            for idx, doc_id in enumerate(ids):
                snippet = documents[idx] if idx < len(documents) else ""
                if snippet:
                    snippet_by_id[doc_id] = snippet
                distance_by_id.setdefault(doc_id, None)
                score_by_id.setdefault(doc_id, None)
                space_by_id.setdefault(doc_id, None)

        matches: list[tuple[str, FileRecord, datetime | None, Path]] = []
        fallback_timestamp = datetime.min.replace(tzinfo=timezone.utc)

        for rel_path, record in state.files.items():
            normalized_rel = _normalise_state_key(rel_path)
            if candidate_ids is not None and record.document_id not in candidate_ids:
                continue
            if name_pattern and not fnmatch.fnmatch(Path(normalized_rel).name, name_pattern):
                continue

            record_tags = [tag for tag in record.tags if tag]
            record_categories = [category for category in record.categories if category]
            record_tags_lower = {tag.lower() for tag in record_tags}
            record_categories_lower = {category.lower() for category in record_categories}

            if tag_filters and not tag_filters.issubset(record_tags_lower):
                continue
            if category_filters and not category_filters.issubset(record_categories_lower):
                continue

            if needs_review is not None and record.needs_review != needs_review:
                continue

            last_modified = record.last_modified
            if last_modified is not None:
                last_modified_utc = (
                    last_modified.astimezone(timezone.utc)
                    if last_modified.tzinfo is not None
                    else last_modified.replace(tzinfo=timezone.utc)
                )
            else:
                last_modified_utc = None

            if before_dt and (last_modified_utc is None or last_modified_utc >= before_dt):
                continue
            if after_dt and (last_modified_utc is None or last_modified_utc < after_dt):
                continue

            if not semantic_mode and query_text:
                haystack = [
                    normalized_rel.lower(),
                    " ".join(record_tags_lower),
                    " ".join(record_categories_lower),
                    (record.rename_suggestion or "").lower(),
                    (record.reasoning or "").lower(),
                ]
                if not any(query_text in field for field in haystack if field):
                    continue

            absolute_path = (root / Path(normalized_rel)).resolve()
            matches.append((normalized_rel, record, last_modified_utc, absolute_path))

        total_matches = len(matches)
        if semantic_mode and candidate_order:
            matches.sort(
                key=lambda entry: candidate_order.get(entry[1].document_id, len(candidate_order))
            )
        else:
            matches.sort(
                key=lambda entry: entry[2] if entry[2] is not None else fallback_timestamp,
                reverse=True,
            )

        displayed_matches = matches[:effective_limit] if effective_limit is not None else matches
        truncated = total_matches - len(displayed_matches)
        displayed_needs_review = sum(
            1 for _, record, _, _ in displayed_matches if record.needs_review
        )

        if search_index is not None:
            missing_doc_ids = [
                record.document_id
                for _, record, _, _ in displayed_matches
                if record.document_id not in snippet_by_id
            ]
            if missing_doc_ids:
                try:
                    response = search_index.fetch(missing_doc_ids, include_documents=True)
                    ids = response.get("ids", []) or []
                    documents = response.get("documents", []) or []
                    for idx, doc_id in enumerate(ids):
                        if doc_id in snippet_by_id:
                            continue
                        snippet = documents[idx] if idx < len(documents) else ""
                        if snippet:
                            snippet_by_id[doc_id] = snippet
                except SearchIndexError as exc:
                    search_warnings.append(f"Unable to load document previews from Chromadb: {exc}")

        json_results = [
            {
                "relative_path": rel_path,
                "absolute_path": str(abs_path),
                "document_id": record.document_id,
                "tags": list(record.tags),
                "categories": list(record.categories),
                "needs_review": record.needs_review,
                "confidence": record.confidence,
                "last_modified": last_modified.isoformat() if last_modified else None,
                "hash": record.hash,
                "rename_suggestion": record.rename_suggestion,
                "snippet": snippet_by_id.get(record.document_id),
                "score": score_by_id.get(record.document_id),
                "distance": distance_by_id.get(record.document_id),
                "space": space_by_id.get(record.document_id),
                "relevance": score_by_id.get(record.document_id),
            }
            for rel_path, record, last_modified, abs_path in displayed_matches
        ]

        counts: dict[str, Any] = {
            "matches": len(displayed_matches),
            "total": total_matches,
            "needs_review": displayed_needs_review,
            "search_enabled": bool(state.search.enabled),
        }
        if effective_limit is not None:
            counts["limit"] = effective_limit
        if truncated > 0:
            counts["truncated"] = truncated

        context_payload = {
            "root": str(root),
            "query": query,
            "name": name_pattern,
            "tags": tag_terms,
            "categories": category_terms,
            "before": before_dt.isoformat() if before_dt else None,
            "after": after_dt.isoformat() if after_dt else None,
            "needs_review": needs_review,
            "limit": effective_limit,
            "contains": contains,
            "search_index": search_status,
        }

        json_payload = {
            "context": context_payload,
            "counts": counts,
            "results": json_results,
        }
        if search_notes or search_warnings:
            json_payload["notes"] = {
                "info": search_notes,
                "warnings": search_warnings,
            }

        if json_enabled:
            console.print_json(data=json_payload)
            return

        if not summary_only:
            for warning in search_warnings:
                _emit_message(
                    f"[yellow]{warning}[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
            for note in search_notes:
                _emit_message(
                    f"[cyan]{note}[/cyan]",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
            if displayed_matches:
                table = Table(
                    title=f"Search results for {root}",
                    box=None,
                    show_edge=False,
                    show_lines=False,
                    pad_edge=False,
                    header_style="bold",
                )
                table.add_column("Path", overflow="fold")
                table.add_column("Modified", overflow="fold")
                for rel_path, _record, last_modified, _ in displayed_matches:
                    parts = rel_path.split("/") if rel_path else []
                    if parts:
                        filename = parts[-1]
                        prefix = "/".join(parts[:-1])
                        if prefix:
                            path_display = f"{prefix}/[bold]{filename}[/bold]"
                        else:
                            path_display = f"[bold]{filename}[/bold]"
                    else:
                        path_display = f"[bold]{rel_path}[/bold]"
                    table.add_row(
                        path_display,
                        _format_modified_timestamp(last_modified),
                    )
                _emit_message(table, mode="detail", quiet=quiet_enabled, summary_only=summary_only)
            else:
                _emit_message(
                    "[yellow]No matching records found.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        if truncated > 0:
            truncated_msg = (
                f"[yellow]{truncated} additional result(s) omitted due to limit "
                f"{effective_limit}.[/yellow]"
            )
            _emit_message(
                truncated_msg,
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        summary_metrics: dict[str, Any] = {
            "matches": len(displayed_matches),
            "total": total_matches,
            "needs_review": displayed_needs_review,
        }
        if effective_limit is not None:
            summary_metrics["limit"] = effective_limit
        if truncated > 0:
            summary_metrics["truncated"] = truncated

        _emit_message(
            _format_summary_line("Search", root, summary_metrics),
            mode="summary",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except MissingStateError as exc:
        _handle_cli_error(
            f"No organization state found for {path}. Run `dorgy org {path}` before searching.",
            code="missing_state",
            json_output=json_enabled,
            original=exc,
        )
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while searching: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


def register_search_command(cli: click.Group) -> None:
    """Register the search command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(search)


__all__ = ["register_search_command", "search"]
