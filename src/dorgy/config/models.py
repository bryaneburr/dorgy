"""Configuration models describing Dorgy settings."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class DorgyBaseModel(BaseModel):
    """Shared configuration for Dorgy Pydantic models."""

    model_config = ConfigDict(extra="forbid")


class LLMSettings(DorgyBaseModel):
    """LLM configuration options.

    Attributes:
        model: Fully-qualified model identifier accepted by LiteLLM/DSPy (e.g.,
            ``"openrouter/gpt-4o-mini"`` or ``"openai/gpt-4o:latest"``).
        api_base_url: Optional override for custom gateways or proxies.
        temperature: Sampling temperature for generative calls.
        max_tokens: Maximum number of tokens in responses.
        api_key: Optional credential supplied to DSPy when required by the backend.
    """

    model: str = "openai/gpt-5"
    api_base_url: Optional[str] = None
    temperature: float = 1.0
    max_tokens: int = 25_000
    api_key: Optional[str] = None

    def runtime_metadata(self) -> dict[str, object]:
        """Return sanitized runtime metadata suitable for logs and JSON payloads."""

        metadata: dict[str, object] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.api_base_url:
            metadata["api_base_url"] = self.api_base_url
        metadata["api_key_configured"] = bool(self.api_key)
        return metadata

    def runtime_summary(self) -> str:
        """Return a human-readable summary of the runtime LLM configuration."""

        parts = [
            f"model={self.model}",
            f"temperature={self.temperature:.2f}",
            f"max_tokens={self.max_tokens}",
        ]
        if self.api_base_url:
            parts.append(f"api_base_url={self.api_base_url}")
        parts.append("api_key=provided" if self.api_key else "api_key=not-set")
        return ", ".join(parts)


class ProcessingOptions(DorgyBaseModel):
    """Processing options governing ingestion behavior.

    Attributes:
        process_images: Whether to enable image captioning/classification.
        preview_char_limit: Maximum number of characters retained in previews provided to
            downstream classifiers.
        process_audio: Whether to process audio files.
        follow_symlinks: Whether to traverse symbolic links.
        process_hidden_files: Whether hidden files should be included.
        recurse_directories: Whether to recurse into subdirectories.
        max_file_size_mb: Maximum file size allowed before skipping.
        sample_size_mb: Sample size limit for oversized files.
        locked_files: Policy describing how to handle locked files.
        corrupted_files: Policy describing how to handle corrupted files.
        watch: Watch configuration controlling debounce and backoff.
        parallel_workers: Maximum number of concurrent worker threads used for ingestion
            and classification tasks.
    """

    process_images: bool = Field(
        default=True,
        validation_alias=AliasChoices("process_images", "use_vision_models"),
    )
    process_audio: bool = False
    follow_symlinks: bool = False
    process_hidden_files: bool = False
    recurse_directories: bool = False
    max_file_size_mb: int = 100
    preview_char_limit: int = Field(default=2048, ge=1)
    sample_size_mb: int = 10
    locked_files: "LockedFilePolicy" = Field(default_factory=lambda: LockedFilePolicy())
    corrupted_files: "CorruptedFilePolicy" = Field(default_factory=lambda: CorruptedFilePolicy())
    watch: "WatchSettings" = Field(default_factory=lambda: WatchSettings())
    parallel_workers: int = Field(
        default=1,
        validation_alias=AliasChoices("parallel_workers", "classification_workers"),
    )


class LockedFilePolicy(DorgyBaseModel):
    """Policy describing how to handle locked files during ingestion.

    Attributes:
        action: Strategy to apply when a file is locked.
        retry_attempts: Number of times to retry when waiting on locks.
        retry_delay_seconds: Delay between retry attempts.
    """

    action: Literal["copy", "skip", "wait"] = "copy"
    retry_attempts: int = 3
    retry_delay_seconds: int = 5


class CorruptedFilePolicy(DorgyBaseModel):
    """Policy describing how to handle corrupted files.

    Attributes:
        action: Strategy to apply when encountering corrupted files.
    """

    action: Literal["skip", "quarantine"] = "skip"


class WatchSettings(DorgyBaseModel):
    """File-system watch configuration.

    Attributes:
        debounce_seconds: Interval to coalesce filesystem events before processing.
        max_batch_interval_seconds: Maximum time to wait before flushing a batch.
        max_batch_items: Maximum number of unique paths in a single batch.
        error_backoff_seconds: Initial backoff delay when processing fails.
        max_error_backoff_seconds: Upper bound for exponential backoff delays.
        allow_deletions: Whether to apply destructive state updates when files are
            deleted or moved outside monitored roots.
    """

    debounce_seconds: float = 2.0
    max_batch_interval_seconds: float = 10.0
    max_batch_items: int = 128
    error_backoff_seconds: float = 5.0
    max_error_backoff_seconds: float = 60.0
    allow_deletions: bool = False


class OrganizationOptions(DorgyBaseModel):
    """Settings that govern post-ingestion organization.

    Attributes:
        conflict_resolution: Strategy to avoid name collisions.
        use_dates: Whether to include dates in destination paths.
        date_format: Format string for date components.
        preserve_language: Whether to retain original language metadata.
        preserve_timestamps: Whether to retain original timestamps.
        preserve_extended_attributes: Whether to retain extended attributes.
        rename_files: Whether to automatically rename files based on classification output.
    """

    conflict_resolution: Literal["append_number", "timestamp", "skip"] = Field(
        default="append_number"
    )
    use_dates: bool = True
    date_format: str = "YYYY-MM"
    preserve_language: bool = False
    preserve_timestamps: bool = True
    preserve_extended_attributes: bool = True
    rename_files: bool = False


class AmbiguitySettings(DorgyBaseModel):
    """Configuration related to ambiguous classification results.

    Attributes:
        confidence_threshold: Minimum confidence required to skip reviews.
        max_auto_categories: Maximum automatic categories to assign.
    """

    confidence_threshold: float = 0.6
    max_auto_categories: int = 3


class LoggingSettings(DorgyBaseModel):
    """Runtime logging configuration.

    Attributes:
        level: Logging verbosity level.
        max_size_mb: Maximum log size before rotation.
        backup_count: Number of historical log files to retain.
    """

    level: str = "WARNING"
    max_size_mb: int = 100
    backup_count: int = 5


class CLIOptions(DorgyBaseModel):
    """CLI behavior defaults and presentation preferences.

    Attributes:
        quiet_default: Whether commands suppress non-error output by default.
        summary_default: Whether commands only print summary lines by default.
        status_history_limit: Default number of status history entries to display.
        progress_enabled: Whether progress indicators are rendered by default.
        search_default_limit: Default result limit for ``dorgy search``.
        move_conflict_strategy: Default conflict resolution strategy for ``dorgy mv``.
    """

    quiet_default: bool = False
    summary_default: bool = False
    status_history_limit: int = 5
    progress_enabled: bool = True
    search_default_limit: int = 20
    move_conflict_strategy: Literal["append_number", "timestamp", "skip"] = "append_number"


class DorgyConfig(DorgyBaseModel):
    """Top-level configuration struct for Dorgy.

    Attributes:
        llm: Language model settings.
        processing: Ingestion processing settings.
        organization: Post-ingestion organization settings.
        ambiguity: Ambiguity-handling settings.
        logging: Logging configuration.
        cli: CLI presentation defaults.
        rules: List of dynamic rule definitions.
    """

    llm: LLMSettings = Field(default_factory=LLMSettings)
    processing: ProcessingOptions = Field(default_factory=ProcessingOptions)
    organization: OrganizationOptions = Field(default_factory=OrganizationOptions)
    ambiguity: AmbiguitySettings = Field(default_factory=AmbiguitySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    cli: CLIOptions = Field(default_factory=CLIOptions)
    rules: List[dict] = Field(default_factory=list)


__all__ = [
    "DorgyBaseModel",
    "LLMSettings",
    "ProcessingOptions",
    "LockedFilePolicy",
    "CorruptedFilePolicy",
    "WatchSettings",
    "OrganizationOptions",
    "AmbiguitySettings",
    "LoggingSettings",
    "CLIOptions",
    "DorgyConfig",
]
