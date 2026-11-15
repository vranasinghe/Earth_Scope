"""Durable background analysis jobs (Phase 6).

Layers
------
* ``models`` / ``db``     — PostgreSQL job records (the authoritative job state).
* ``queue``               — RQ (Redis) delivery of "run job X" messages.
* ``coordination``        — Redis-wide NASA POWER concurrency and request-rate limits.
* ``artifacts``           — checkpoints and published results on durable storage.
* ``service``             — submission, idempotency, ownership, budgets, cancel / retry.
* ``pipeline`` / ``worker`` — the checkpointed processing stages run by RQ workers.
* ``reconciler``          — outbox re-enqueue, orphaned-job recovery, expiry.

The scientific work is NOT re-implemented here: the worker calls the same
geometry, tiling, merge, aggregation, statistics and FDR functions as the
synchronous endpoints.
"""

# Bumped whenever background processing could change a published number.
ANALYSIS_ENGINE_VERSION = "earthscope-analysis-6.0.0"
