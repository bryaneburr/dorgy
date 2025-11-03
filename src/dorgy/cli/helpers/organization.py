"""Organization pipeline helpers shared across CLI commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from dorgy.classification import ClassificationBatch

if TYPE_CHECKING:
    from dorgy.organization.models import OperationPlan


def compute_org_counts(
    result: Any,
    classification_batch: ClassificationBatch,
    plan: "OperationPlan",
) -> dict[str, int]:
    """Return a summary of organization metrics for reporting."""

    ingestion_errors = len(result.errors)
    classification_errors = len(classification_batch.errors)
    conflict_count = sum(1 for operation in plan.renames if operation.conflict_applied)
    conflict_count += sum(1 for operation in plan.moves if operation.conflict_applied)

    return {
        "processed": len(result.processed),
        "needs_review": len(result.needs_review),
        "quarantined": len(result.quarantined),
        "renames": len(plan.renames),
        "moves": len(plan.moves),
        "metadata_updates": len(plan.metadata_updates),
        "deletes": len(plan.deletes),
        "conflicts": conflict_count,
        "ingestion_errors": ingestion_errors,
        "classification_errors": classification_errors,
        "errors": ingestion_errors + classification_errors,
    }


def collect_error_payload(
    result: Any,
    classification_batch: ClassificationBatch,
) -> dict[str, list[str]]:
    """Collect structured error payloads for ingestion and classification."""

    return {
        "ingestion": list(result.errors),
        "classification": list(classification_batch.errors),
    }


__all__ = ["collect_error_payload", "compute_org_counts"]
