"""A simulated CRM world, owned by the evaluator, backed by stdlib SQLite.

The v1 harness graded what the qualifier SAID (its parsed JSON). v2 grades
what HAPPENED: the runner applies each accepted qualification decision to
this CRM through a narrow write API, and the offline grader later reads
the resulting state - the tier actually assigned to the lead record, the
queue the lead is actually a member of, and the dispatch event with its
receipt - instead of trusting the runner's own log.

One database file holds one isolated world per (arm, run). A world is
seeded with its lead roster (every lead unqualified, in the `unrouted`
queue) immediately before that arm/run starts; only one world is open for
writing at a time; a write that names a lead or trial from another world
is refused.

Honest boundary: this is a local simulator that the harness itself owns.
It is not a production CRM and not an independent security boundary. The
only separation that means anything is from the model under test, which
runs tool-free and never sees this file, the truth labels, or the plan.
Whoever owns the filesystem can rewrite the database and every hash.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import sqlite3
from typing import Any, Dict, Iterator, List, Optional, Sequence

from . import integrity
from .pipeline import ROUTES, TIERS

SCHEMA_VERSION = "gtm-crm-world/1"
UNROUTED = "unrouted"
QUEUES = [UNROUTED] + list(ROUTES)
EVENT_APPLIED = "qualification_applied"
EVENT_REJECTED = "decision_rejected"
EVENT_KINDS = [EVENT_APPLIED, EVENT_REJECTED]
REJECTION_REASONS = ["parse_failure"]

EXPECTED_SCHEMA = {
    "meta": ["key", "value"],
    "worlds": ["world_id", "arm", "run_index", "seeded_leads", "state"],
    "crm_leads": ["world_id", "lead_id", "tier"],
    "queue_membership": ["world_id", "lead_id", "queue"],
    "events": ["seq", "world_id", "lead_id", "trial_id", "kind", "tier",
               "queue", "detail", "receipt"],
}


def _quoted(values: Sequence[str]) -> str:
    return ", ".join("'" + v + "'" for v in values)


_DDL = f"""
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE worlds (
    world_id TEXT PRIMARY KEY,
    arm TEXT NOT NULL,
    run_index INTEGER NOT NULL,
    seeded_leads INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'closed')),
    UNIQUE (arm, run_index)
);
CREATE TABLE crm_leads (
    world_id TEXT NOT NULL REFERENCES worlds (world_id),
    lead_id TEXT NOT NULL,
    tier TEXT CHECK (tier IS NULL OR tier IN ({_quoted(TIERS)})),
    PRIMARY KEY (world_id, lead_id)
);
CREATE TABLE queue_membership (
    world_id TEXT NOT NULL,
    lead_id TEXT NOT NULL,
    queue TEXT NOT NULL CHECK (queue IN ({_quoted(QUEUES)})),
    PRIMARY KEY (world_id, lead_id, queue),
    FOREIGN KEY (world_id, lead_id)
        REFERENCES crm_leads (world_id, lead_id)
);
CREATE TABLE events (
    seq INTEGER PRIMARY KEY,
    world_id TEXT NOT NULL,
    lead_id TEXT NOT NULL,
    trial_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ({_quoted(EVENT_KINDS)})),
    tier TEXT,
    queue TEXT,
    detail TEXT,
    receipt TEXT NOT NULL UNIQUE,
    FOREIGN KEY (world_id, lead_id)
        REFERENCES crm_leads (world_id, lead_id)
);
"""


class CRMError(RuntimeError):
    """The CRM refused a write. No state was changed."""


def world_id_for(arm: str, run_index: int) -> str:
    return f"{arm}/r{run_index}"


def trial_id_for(arm: str, run_index: int, lead_id: str) -> str:
    return f"{world_id_for(arm, run_index)}/{lead_id}"


def chain_genesis(plan_sha256: str, receipt_sha256: str) -> str:
    """First link of the event-receipt chain: binds events to one plan and
    one run receipt."""
    return integrity.sha256_canonical(
        {"genesis": SCHEMA_VERSION, "plan_sha256": plan_sha256,
         "receipt_sha256": receipt_sha256})


def event_receipt(prev: str, event: Dict[str, Any]) -> str:
    """Receipt for one event: a hash over the previous receipt and the
    event's own fields. Recomputable by the grader; a consistency link,
    not a signature."""
    return integrity.sha256_canonical({
        "prev": prev,
        "seq": event["seq"],
        "world_id": event["world_id"],
        "lead_id": event["lead_id"],
        "trial_id": event["trial_id"],
        "kind": event["kind"],
        "tier": event["tier"],
        "queue": event["queue"],
        "detail": event["detail"],
    })


class CRMWorld:
    """Evaluator-side owner of the world database (create, seed, seal)."""

    def __init__(self, path: str, conn: sqlite3.Connection):
        self.path = path
        self._conn = conn
        self._open_world: Optional[str] = None

    @classmethod
    def create(cls, path: str, plan_sha256: str, dataset_sha256: str,
               receipt_sha256: str) -> "CRMWorld":
        if os.path.exists(path):
            raise CRMError(f"refusing to reuse an existing world: {path}")
        conn = sqlite3.connect(path, isolation_level=None)
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA foreign_keys = ON")
        world = cls(path, conn)
        with world._tx():
            for statement in _DDL.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [("schema_version", SCHEMA_VERSION),
                 ("plan_sha256", plan_sha256),
                 ("dataset_sha256", dataset_sha256),
                 ("receipt_sha256", receipt_sha256),
                 ("chain_genesis",
                  chain_genesis(plan_sha256, receipt_sha256)),
                 ("state", "open")])
        return world

    @contextlib.contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """All-or-nothing write. Any exception rolls the whole thing back."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        self._conn.execute("COMMIT")

    def _meta(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def open_world(self, arm: str, run_index: int,
                   lead_ids: Sequence[str]) -> "WorldHandle":
        """Seed a fresh world for one (arm, run) and open it for writes."""
        if self._meta("state") != "open":
            raise CRMError("database is sealed; no new worlds")
        if self._open_world is not None:
            raise CRMError(
                f"world {self._open_world} is still open; one world at a "
                "time")
        if integrity.find_duplicates(lead_ids):
            raise CRMError("duplicate lead ids in world roster")
        world_id = world_id_for(arm, run_index)
        try:
            with self._tx() as conn:
                conn.execute(
                    "INSERT INTO worlds (world_id, arm, run_index, "
                    "seeded_leads, state) VALUES (?, ?, ?, ?, 'open')",
                    (world_id, arm, run_index, len(lead_ids)))
                conn.executemany(
                    "INSERT INTO crm_leads (world_id, lead_id, tier) "
                    "VALUES (?, ?, NULL)",
                    [(world_id, lead_id) for lead_id in lead_ids])
                conn.executemany(
                    "INSERT INTO queue_membership (world_id, lead_id, "
                    "queue) VALUES (?, ?, ?)",
                    [(world_id, lead_id, UNROUTED) for lead_id in lead_ids])
        except sqlite3.IntegrityError as exc:
            raise CRMError(f"cannot seed world {world_id}: {exc}") from exc
        self._open_world = world_id
        return WorldHandle(self, world_id)

    def seal(self) -> Dict[str, Any]:
        """Mark the database complete and close it. Requires every world
        to be closed. Returns the event-chain head and event count."""
        if self._open_world is not None:
            raise CRMError(f"world {self._open_world} is still open")
        with self._tx() as conn:
            row = conn.execute(
                "SELECT receipt, seq FROM events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            head = row[0] if row else self._meta("chain_genesis")
            count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            conn.execute("UPDATE meta SET value = 'sealed' "
                         "WHERE key = 'state'")
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [("event_chain_head", head), ("event_count", str(count))])
        self.close()
        return {"event_chain_head": head, "event_count": count}

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class WorldHandle:
    """The narrow write surface for ONE (arm, run) world.

    Two operations only: apply an accepted qualification decision, or
    record that a decision was rejected (unparseable). Each is a single
    transaction. Truth labels are never passed in and never stored.
    """

    def __init__(self, crm: CRMWorld, world_id: str):
        self._crm = crm
        self.world_id = world_id

    def _check_open(self) -> None:
        if self._crm._open_world != self.world_id:
            raise CRMError(f"world {self.world_id} is not open for writes")

    def _check_target(self, conn: sqlite3.Connection, trial_id: str,
                      lead_id: str) -> None:
        if trial_id != f"{self.world_id}/{lead_id}":
            raise CRMError(
                f"trial {trial_id!r} does not belong to world "
                f"{self.world_id!r} / lead {lead_id!r}")
        row = conn.execute(
            "SELECT tier FROM crm_leads WHERE world_id = ? AND lead_id = ?",
            (self.world_id, lead_id)).fetchone()
        if row is None:
            raise CRMError(
                f"unknown lead {lead_id!r} in world {self.world_id!r}")
        seen = conn.execute(
            "SELECT COUNT(*) FROM events WHERE world_id = ? AND lead_id = ?",
            (self.world_id, lead_id)).fetchone()[0]
        if seen or row[0] is not None:
            raise CRMError(
                f"lead {lead_id!r} in world {self.world_id!r} already has "
                "a recorded outcome")

    def _append_event(self, conn: sqlite3.Connection, trial_id: str,
                      lead_id: str, kind: str, tier: Optional[str],
                      queue: Optional[str], detail: Optional[str]) -> str:
        last = conn.execute(
            "SELECT seq, receipt FROM events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        if last:
            seq, prev = last[0] + 1, last[1]
        else:
            seq, prev = 1, self._crm._meta("chain_genesis")
        event = {"seq": seq, "world_id": self.world_id, "lead_id": lead_id,
                 "trial_id": trial_id, "kind": kind, "tier": tier,
                 "queue": queue, "detail": detail}
        receipt = event_receipt(prev, event)
        conn.execute(
            "INSERT INTO events (seq, world_id, lead_id, trial_id, kind, "
            "tier, queue, detail, receipt) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (seq, self.world_id, lead_id, trial_id, kind, tier, queue,
             detail, receipt))
        return receipt

    def apply_qualification(self, trial_id: str, lead_id: str, tier: str,
                            route: str) -> str:
        """Assign the tier, move the lead into the route's queue, and
        record the dispatch event - all in one transaction. Returns the
        event receipt. Raises CRMError (no state change) otherwise."""
        self._check_open()
        if tier not in TIERS:
            raise CRMError(f"invalid tier: {tier!r}")
        if route not in ROUTES:
            raise CRMError(f"invalid route: {route!r}")
        with self._crm._tx() as conn:
            self._check_target(conn, trial_id, lead_id)
            conn.execute(
                "UPDATE crm_leads SET tier = ? WHERE world_id = ? AND "
                "lead_id = ?", (tier, self.world_id, lead_id))
            conn.execute(
                "DELETE FROM queue_membership WHERE world_id = ? AND "
                "lead_id = ?", (self.world_id, lead_id))
            conn.execute(
                "INSERT INTO queue_membership (world_id, lead_id, queue) "
                "VALUES (?, ?, ?)", (self.world_id, lead_id, route))
            return self._append_event(conn, trial_id, lead_id,
                                      EVENT_APPLIED, tier, route, None)

    def record_rejection(self, trial_id: str, lead_id: str,
                         reason_code: str) -> str:
        """Record that no usable decision arrived for this lead. The lead
        stays unqualified and unrouted; the grader counts it as a failure
        in every denominator."""
        self._check_open()
        if reason_code not in REJECTION_REASONS:
            raise CRMError(f"invalid rejection reason: {reason_code!r}")
        with self._crm._tx() as conn:
            self._check_target(conn, trial_id, lead_id)
            return self._append_event(conn, trial_id, lead_id,
                                      EVENT_REJECTED, None, None,
                                      reason_code)

    def close(self) -> None:
        self._check_open()
        with self._crm._tx() as conn:
            conn.execute("UPDATE worlds SET state = 'closed' "
                         "WHERE world_id = ?", (self.world_id,))
        self._crm._open_world = None


def read_snapshot(path: str) -> Dict[str, Any]:
    """Read the whole persisted world, read-only, into plain structures.

    Raises IntegrityError if the file is not a readable SQLite database
    with exactly the expected tables and columns. The grader re-validates
    every row in Python: constraints inside a file are not trusted.
    """
    if not os.path.isfile(path):
        raise integrity.IntegrityError(f"world database missing: {path}")
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.exists(path + suffix):
            raise integrity.IntegrityError(
                f"world database has a leftover {suffix} file: it was not "
                "closed cleanly")
    uri = pathlib.Path(path).resolve().as_uri() + "?mode=ro&immutable=1"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise integrity.IntegrityError(
            f"cannot open world database: {exc}") from exc
    try:
        check = conn.execute("PRAGMA integrity_check").fetchall()
        if check != [("ok",)]:
            raise integrity.IntegrityError(
                f"world database fails integrity_check: {check[:3]}")
        objects = conn.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_autoindex_%'").fetchall()
        tables = sorted(name for kind, name in objects if kind == "table")
        others = sorted(name for kind, name in objects if kind != "table")
        if tables != sorted(EXPECTED_SCHEMA) or others:
            raise integrity.IntegrityError(
                f"unexpected world schema: tables={tables} other={others}")
        for table, columns in EXPECTED_SCHEMA.items():
            found = [row[1] for row in
                     conn.execute(f"PRAGMA table_info({table})")]
            if found != columns:
                raise integrity.IntegrityError(
                    f"unexpected columns in {table}: {found}")
        meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
        if integrity.find_duplicates(k for k, _ in meta_rows):
            raise integrity.IntegrityError("duplicate meta keys in world")
        snapshot = {
            "meta": dict(meta_rows),
            "worlds": [
                {"world_id": r[0], "arm": r[1], "run_index": r[2],
                 "seeded_leads": r[3], "state": r[4]}
                for r in conn.execute(
                    "SELECT world_id, arm, run_index, seeded_leads, state "
                    "FROM worlds ORDER BY rowid")],
            "leads": [
                {"world_id": r[0], "lead_id": r[1], "tier": r[2]}
                for r in conn.execute(
                    "SELECT world_id, lead_id, tier FROM crm_leads "
                    "ORDER BY rowid")],
            "queues": [
                {"world_id": r[0], "lead_id": r[1], "queue": r[2]}
                for r in conn.execute(
                    "SELECT world_id, lead_id, queue FROM queue_membership "
                    "ORDER BY rowid")],
            "events": [
                {"seq": r[0], "world_id": r[1], "lead_id": r[2],
                 "trial_id": r[3], "kind": r[4], "tier": r[5],
                 "queue": r[6], "detail": r[7], "receipt": r[8]}
                for r in conn.execute(
                    "SELECT seq, world_id, lead_id, trial_id, kind, tier, "
                    "queue, detail, receipt FROM events ORDER BY seq")],
        }
    except sqlite3.Error as exc:
        raise integrity.IntegrityError(
            f"world database is unreadable: {exc}") from exc
    finally:
        conn.close()
    return snapshot
