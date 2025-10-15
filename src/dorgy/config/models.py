"""Configuration model placeholders for Phase 0 scaffolding."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DorgyBaseModel(BaseModel):
    """Shared configuration for Dorgy Pydantic models."""

    model_config = ConfigDict(extra="forbid")


class LLMSettings(DorgyBaseModel):
    """LLM configuration stub; values to be refined in Phase 1."""

    provider: str = "local"
    model: str = "llama3"
    temperature: float = 0.1
    max_tokens: int = 2_000
    api_key: Optional[str] = None


class ProcessingOptions(DorgyBaseModel):
    """Placeholder processing options matching high-level SPEC expectations."""

    use_vision_models: bool = False
    process_audio: bool = False
    follow_symlinks: bool = False
    process_hidden_files: bool = False
    max_file_size_mb: int = 100
    sample_size_mb: int = 10


class OrganizationOptions(DorgyBaseModel):
    """Placeholder organization settings."""

    conflict_resolution: str = Field(default="append_number")
    use_dates: bool = True
    date_format: str = "YYYY-MM"
    preserve_language: bool = False
    preserve_timestamps: bool = True
    preserve_extended_attributes: bool = True


class AmbiguitySettings(DorgyBaseModel):
    confidence_threshold: float = 0.8
    max_auto_categories: int = 3


class LoggingSettings(DorgyBaseModel):
    level: str = "WARNING"
    max_size_mb: int = 100
    backup_count: int = 5


class DorgyConfig(DorgyBaseModel):
    """Top-level configuration model stub."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    processing: ProcessingOptions = Field(default_factory=ProcessingOptions)
    organization: OrganizationOptions = Field(default_factory=OrganizationOptions)
    ambiguity: AmbiguitySettings = Field(default_factory=AmbiguitySettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    rules: List[dict] = Field(default_factory=list)


__all__ = [
    "DorgyBaseModel",
    "LLMSettings",
    "ProcessingOptions",
    "OrganizationOptions",
    "AmbiguitySettings",
    "LoggingSettings",
    "DorgyConfig",
]
