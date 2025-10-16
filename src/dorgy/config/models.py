"""Configuration models describing Dorgy settings."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DorgyBaseModel(BaseModel):
    """Shared configuration for Dorgy Pydantic models."""

    model_config = ConfigDict(extra="forbid")


class LLMSettings(DorgyBaseModel):
    """LLM configuration options.

    Attributes:
        provider: Identifier for the language-model provider.
        model: Model name to target when issuing requests.
        temperature: Sampling temperature for generative calls.
        max_tokens: Maximum number of tokens in responses.
        api_key: Optional credential for hosted providers.
    """

    provider: str = "local"
    model: str = "llama3"
    temperature: float = 0.1
    max_tokens: int = 2_000
    api_key: Optional[str] = None


class ProcessingOptions(DorgyBaseModel):
    """Processing options governing ingestion behavior.

    Attributes:
        use_vision_models: Whether to enable vision-based classification.
        process_audio: Whether to process audio files.
        follow_symlinks: Whether to traverse symbolic links.
        process_hidden_files: Whether hidden files should be included.
        recurse_directories: Whether to recurse into subdirectories.
        max_file_size_mb: Maximum file size allowed before skipping.
        sample_size_mb: Sample size limit for oversized files.
        locked_files: Policy describing how to handle locked files.
        corrupted_files: Policy describing how to handle corrupted files.
    """

    use_vision_models: bool = False
    process_audio: bool = False
    follow_symlinks: bool = False
    process_hidden_files: bool = False
    recurse_directories: bool = False
    max_file_size_mb: int = 100
    sample_size_mb: int = 10
    locked_files: "LockedFilePolicy" = Field(default_factory=lambda: LockedFilePolicy())
    corrupted_files: "CorruptedFilePolicy" = Field(default_factory=lambda: CorruptedFilePolicy())


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
    rename_files: bool = True


class AmbiguitySettings(DorgyBaseModel):
    """Configuration related to ambiguous classification results.

    Attributes:
        confidence_threshold: Minimum confidence required to skip reviews.
        max_auto_categories: Maximum automatic categories to assign.
    """

    confidence_threshold: float = 0.8
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
    """

    quiet_default: bool = False
    summary_default: bool = False
    status_history_limit: int = 5


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
    "OrganizationOptions",
    "AmbiguitySettings",
    "LoggingSettings",
    "CLIOptions",
    "DorgyConfig",
]
