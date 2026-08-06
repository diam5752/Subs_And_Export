"""Canonical media-job lifecycle state sets."""

ACTIVE_JOB_STATUSES = frozenset({"pending", "processing", "cancelling"})
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})
CANCELLABLE_JOB_STATUSES = frozenset({"pending", "processing"})
