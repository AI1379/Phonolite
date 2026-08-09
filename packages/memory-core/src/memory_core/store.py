"""SQLite event ledger and deterministic memory projections.

Raw events are append-only. Observations, claims, project state, and learning
state are rebuildable projections, which makes replay tests useful instead of
merely checking that rows can be inserted.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from memory_core.models import (
    ClaimState,
    ClaimStatus,
    ClaimType,
    ExperimentOutcome,
    JsonObject,
    JsonValue,
    LearningState,
    MemoryClaim,
    MemoryEvent,
    MemoryPolicy,
    Observation,
    OutcomeProjection,
    ProjectStateEntry,
    Sensitivity,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _json_dump(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _json_value(raw: str) -> JsonValue:
    return cast(JsonValue, json.loads(raw))


def _json_object(raw: str) -> JsonObject:
    value = _json_value(raw)
    if not isinstance(value, dict):
        raise ValueError("stored JSON value is not an object")
    return value


def _required_str(payload: JsonObject, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"event payload requires non-empty string {key!r}")
    return value


def _optional_str(payload: JsonObject, key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"event payload {key!r} must be a string or null")
    return value


def _number(payload: JsonObject, key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"event payload {key!r} must be numeric")
    return float(value)


def _object(payload: JsonObject, key: str) -> JsonObject:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"event payload {key!r} must be an object")
    return value


def _strings(payload: JsonObject, key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"event payload {key!r} must be an array of strings")
    return tuple(cast(list[str], value))


class SQLiteMemoryStore:
    """Append-only memory ledger with replayable SQLite projections."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        path_text = str(path)
        if path_text != ":memory:":
            Path(path_text).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path_text, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._connection.close()

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
        with self._connection:
            yield self._connection

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                project_id TEXT,
                payload_json TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                source_event_id TEXT NOT NULL REFERENCES memory_events(id),
                subject TEXT NOT NULL,
                event_text TEXT NOT NULL,
                context TEXT,
                confidence REAL NOT NULL,
                observed_at TEXT NOT NULL,
                project_id TEXT
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                value_json TEXT NOT NULL,
                context_type TEXT,
                context_id TEXT,
                claim_type TEXT NOT NULL,
                tags_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_evidence (
                claim_id TEXT NOT NULL REFERENCES claims(id),
                event_id TEXT NOT NULL REFERENCES memory_events(id),
                excerpt TEXT,
                extractor TEXT NOT NULL,
                weight REAL NOT NULL,
                observed_at TEXT NOT NULL,
                PRIMARY KEY (claim_id, event_id)
            );
            CREATE TABLE IF NOT EXISTS claim_states (
                claim_id TEXT PRIMARY KEY REFERENCES claims(id),
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                valid_from TEXT,
                valid_until TEXT,
                superseded_by TEXT,
                last_confirmed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS memory_policies (
                claim_id TEXT PRIMARY KEY REFERENCES claims(id),
                owner_id TEXT NOT NULL,
                visibility TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                allowed_contexts_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_state (
                project_id TEXT NOT NULL,
                state_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                source_event_id TEXT NOT NULL REFERENCES memory_events(id),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project_id, state_key)
            );
            CREATE TABLE IF NOT EXISTS learning_state (
                subject_id TEXT NOT NULL,
                project_key TEXT NOT NULL,
                focus TEXT NOT NULL,
                status TEXT NOT NULL,
                mastery REAL NOT NULL,
                evidence_count INTEGER NOT NULL,
                source_event_id TEXT NOT NULL REFERENCES memory_events(id),
                updated_at TEXT NOT NULL,
                PRIMARY KEY (subject_id, project_key, focus)
            );
            """
        )

    # -- immutable event ledger ----------------------------------------- #
    def append_event(self, event: MemoryEvent, *, project: bool = True) -> MemoryEvent:
        """Append an event exactly once and optionally update projections."""
        try:
            with self._transaction() as connection:
                connection.execute(
                    """INSERT INTO memory_events
                       (id, event_type, actor_id, project_id, payload_json, occurred_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        event.id,
                        event.event_type,
                        event.actor_id,
                        event.project_id,
                        _json_dump(event.payload),
                        event.occurred_at,
                    ),
                )
                if project:
                    self._project_event(connection, event)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"memory event already exists: {event.id}") from exc
        return event

    def record_event(
        self,
        *,
        event_type: str,
        actor_id: str,
        project_id: str | None,
        payload: JsonObject,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> MemoryEvent:
        event = MemoryEvent(
            id=event_id or _new_id("event"),
            event_type=event_type,
            actor_id=actor_id,
            project_id=project_id,
            payload=payload,
            occurred_at=occurred_at or _now_iso(),
        )
        return self.append_event(event)

    def get_event(self, event_id: str) -> MemoryEvent:
        row = self._connection.execute(
            "SELECT * FROM memory_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"memory event not found: {event_id}")
        return self._event_from_row(row)

    def list_events(self, *, project_id: str | None = None) -> list[MemoryEvent]:
        if project_id is None:
            rows = self._connection.execute(
                "SELECT * FROM memory_events ORDER BY seq"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM memory_events WHERE project_id = ? ORDER BY seq",
                (project_id,),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> MemoryEvent:
        return MemoryEvent(
            id=cast(str, row["id"]),
            event_type=cast(str, row["event_type"]),
            actor_id=cast(str, row["actor_id"]),
            project_id=cast(str | None, row["project_id"]),
            payload=_json_object(cast(str, row["payload_json"])),
            occurred_at=cast(str, row["occurred_at"]),
        )

    # -- commands represented as events --------------------------------- #
    def record_episode(
        self,
        *,
        actor_id: str,
        project_id: str | None,
        summary: str,
        details: JsonObject | None = None,
    ) -> MemoryEvent:
        return self.record_event(
            event_type="episode.recorded",
            actor_id=actor_id,
            project_id=project_id,
            payload={"summary": summary, "details": details or {}},
        )

    def record_observation(
        self,
        *,
        actor_id: str,
        project_id: str | None,
        subject: str,
        event: str,
        context: str | None,
        confidence: float,
    ) -> Observation:
        self._validate_confidence(confidence)
        source = self.record_event(
            event_type="observation.recorded",
            actor_id=actor_id,
            project_id=project_id,
            payload={
                "subject": subject,
                "event": event,
                "context": context,
                "confidence": confidence,
            },
        )
        return self.get_observation(f"observation:{source.id}")

    def propose_claim(
        self,
        *,
        actor_id: str,
        project_id: str | None,
        subject_type: str,
        subject_id: str,
        predicate: str,
        value: JsonObject,
        claim_type: ClaimType,
        context_type: str | None = None,
        context_id: str | None = None,
        tags: tuple[str, ...] = (),
        confidence: float = 0.5,
        excerpt: str | None = None,
        extractor: str = "explicit-tool",
        sensitivity: str = Sensitivity.PRIVATE.value,
        visibility: str = "private",
        allowed_contexts: tuple[str, ...] = (),
        claim_id: str | None = None,
    ) -> MemoryClaim:
        self._validate_confidence(confidence)
        resolved_claim_id = claim_id or _new_id("claim")
        self.record_event(
            event_type="claim.proposed",
            actor_id=actor_id,
            project_id=project_id,
            payload={
                "claim_id": resolved_claim_id,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "predicate": predicate,
                "value": value,
                "context_type": context_type,
                "context_id": context_id,
                "claim_type": claim_type.value,
                "tags": list(tags),
                "confidence": confidence,
                "excerpt": excerpt,
                "extractor": extractor,
                "sensitivity": sensitivity,
                "visibility": visibility,
                "allowed_contexts": list(allowed_contexts),
            },
        )
        return self.get_claim(resolved_claim_id)[0]

    def confirm_claim(self, claim_id: str, *, actor_id: str) -> ClaimState:
        claim, _, _ = self.get_claim(claim_id)
        self.record_event(
            event_type="claim.confirmed",
            actor_id=actor_id,
            project_id=claim.context_id if claim.context_type == "project" else None,
            payload={"claim_id": claim_id},
        )
        return self.get_claim(claim_id)[1]

    def record_learning_outcome(
        self,
        *,
        actor_id: str,
        subject_id: str,
        project_id: str | None,
        focus: str,
        status: str,
        mastery: float,
        evidence: str | None = None,
    ) -> LearningState:
        self._validate_confidence(mastery)
        self.record_event(
            event_type="learning.outcome",
            actor_id=actor_id,
            project_id=project_id,
            payload={
                "subject_id": subject_id,
                "focus": focus,
                "status": status,
                "mastery": mastery,
                "evidence": evidence,
            },
        )
        return self.get_learning_state(subject_id, focus, project_id=project_id)

    def record_project_state(
        self,
        *,
        actor_id: str,
        project_id: str,
        key: str,
        value: JsonValue,
    ) -> ProjectStateEntry:
        """Explicitly update a project-state projection through the event log."""
        event = self.record_event(
            event_type="project.state_updated",
            actor_id=actor_id,
            project_id=project_id,
            payload={"key": key, "value": value},
        )
        return next(
            item for item in self.list_project_state(project_id) if item.key == key
            and item.source_event_id == event.id
        )

    def record_experiment_outcome(
        self, outcome: ExperimentOutcome, *, actor_id: str = "person:user"
    ) -> OutcomeProjection:
        event = self.record_event(
            event_type="experiment.outcome",
            actor_id=actor_id,
            project_id=outcome.project_id,
            payload={
                "subject_id": outcome.subject_id,
                "experiment_id": outcome.experiment_id,
                "chosen_version_id": outcome.chosen_version_id,
                "reason": outcome.reason,
                "learning_focus": outcome.learning_focus,
                "tags": list(outcome.tags),
            },
        )
        return OutcomeProjection(
            event=event,
            observation_id=f"observation:{event.id}",
            decision_claim_id=f"claim:decision:{event.id}",
            preference_claim_id=(
                f"claim:preference:{event.id}" if outcome.reason else None
            ),
            learning_focus=outcome.learning_focus,
        )

    @staticmethod
    def _validate_confidence(value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence/mastery must be between 0.0 and 1.0")

    # -- projections ----------------------------------------------------- #
    def replay(self) -> None:
        """Rebuild every derived table deterministically from raw events."""
        events = self.list_events()
        with self._transaction() as connection:
            connection.execute("DELETE FROM claim_evidence")
            connection.execute("DELETE FROM claim_states")
            connection.execute("DELETE FROM memory_policies")
            connection.execute("DELETE FROM claims")
            connection.execute("DELETE FROM observations")
            connection.execute("DELETE FROM project_state")
            connection.execute("DELETE FROM learning_state")
            for event in events:
                self._project_event(connection, event)

    def _project_event(self, connection: sqlite3.Connection, event: MemoryEvent) -> None:
        if event.event_type == "episode.recorded":
            self._insert_observation(
                connection,
                event,
                observation_id=f"observation:{event.id}",
                subject=event.actor_id,
                event_text=_required_str(event.payload, "summary"),
                context=(f"project:{event.project_id}" if event.project_id else None),
                confidence=1.0,
            )
        elif event.event_type == "observation.recorded":
            self._insert_observation(
                connection,
                event,
                observation_id=f"observation:{event.id}",
                subject=_required_str(event.payload, "subject"),
                event_text=_required_str(event.payload, "event"),
                context=_optional_str(event.payload, "context"),
                confidence=_number(event.payload, "confidence"),
            )
        elif event.event_type == "claim.proposed":
            self._project_claim_proposed(connection, event)
        elif event.event_type == "claim.confirmed":
            claim_id = _required_str(event.payload, "claim_id")
            cursor = connection.execute(
                """UPDATE claim_states
                   SET status = ?, confidence = 1.0, last_confirmed_at = ?
                   WHERE claim_id = ?""",
                (ClaimStatus.CONFIRMED.value, event.occurred_at, claim_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"cannot confirm unknown claim: {claim_id}")
        elif event.event_type == "learning.outcome":
            self._project_learning_outcome(connection, event)
        elif event.event_type == "project.state_updated":
            if event.project_id is None:
                raise ValueError("project state update requires project_id")
            self._upsert_project_state(
                connection,
                project_id=event.project_id,
                key=_required_str(event.payload, "key"),
                value=event.payload.get("value"),
                event=event,
            )
        elif event.event_type == "experiment.outcome":
            self._project_experiment_outcome(connection, event)

    def _project_claim_proposed(
        self, connection: sqlite3.Connection, event: MemoryEvent
    ) -> None:
        payload = event.payload
        claim_type = ClaimType(_required_str(payload, "claim_type"))
        raw_sensitivity = _required_str(payload, "sensitivity")
        try:
            sensitivity = Sensitivity(raw_sensitivity)
        except ValueError:
            sensitivity = Sensitivity.QUARANTINE
        visibility = _required_str(payload, "visibility")
        if sensitivity is Sensitivity.QUARANTINE:
            visibility = "private"
        self._insert_claim(
            connection,
            event=event,
            claim_id=_required_str(payload, "claim_id"),
            subject_type=_required_str(payload, "subject_type"),
            subject_id=_required_str(payload, "subject_id"),
            predicate=_required_str(payload, "predicate"),
            value=_object(payload, "value"),
            context_type=_optional_str(payload, "context_type"),
            context_id=_optional_str(payload, "context_id"),
            claim_type=claim_type,
            tags=_strings(payload, "tags"),
            status=ClaimStatus.PROPOSED,
            confidence=_number(payload, "confidence"),
            owner_id=event.actor_id,
            visibility=visibility,
            sensitivity=sensitivity,
            allowed_contexts=_strings(payload, "allowed_contexts"),
            excerpt=_optional_str(payload, "excerpt"),
            extractor=_required_str(payload, "extractor"),
        )

    def _project_learning_outcome(
        self, connection: sqlite3.Connection, event: MemoryEvent
    ) -> None:
        subject_id = _required_str(event.payload, "subject_id")
        focus = _required_str(event.payload, "focus")
        self._upsert_learning_state(
            connection,
            subject_id=subject_id,
            project_id=event.project_id,
            focus=focus,
            status=_required_str(event.payload, "status"),
            mastery=_number(event.payload, "mastery"),
            source_event_id=event.id,
            updated_at=event.occurred_at,
        )
        evidence = _optional_str(event.payload, "evidence")
        self._insert_observation(
            connection,
            event,
            observation_id=f"observation:{event.id}",
            subject=f"person:{subject_id}",
            event_text=evidence or f"Recorded learning outcome for {focus}",
            context=f"learning:{focus}",
            confidence=1.0,
        )

    def _project_experiment_outcome(
        self, connection: sqlite3.Connection, event: MemoryEvent
    ) -> None:
        if event.project_id is None:
            raise ValueError("experiment outcome requires project_id")
        payload = event.payload
        subject_id = _required_str(payload, "subject_id")
        experiment_id = _required_str(payload, "experiment_id")
        version_id = _required_str(payload, "chosen_version_id")
        reason = _optional_str(payload, "reason")
        learning_focus = _optional_str(payload, "learning_focus")
        tags = _strings(payload, "tags")
        context = f"experiment:{experiment_id}"
        self._insert_observation(
            connection,
            event,
            observation_id=f"observation:{event.id}",
            subject=f"person:{subject_id}",
            event_text=f"Selected version {version_id} in experiment {experiment_id}",
            context=context,
            confidence=1.0,
        )
        self._insert_claim(
            connection,
            event=event,
            claim_id=f"claim:decision:{event.id}",
            subject_type="project",
            subject_id=event.project_id,
            predicate="selected_experiment_variant",
            value={
                "experiment_id": experiment_id,
                "version_id": version_id,
                "reason": reason,
            },
            context_type="experiment",
            context_id=experiment_id,
            claim_type=ClaimType.DECISION,
            tags=tags,
            status=ClaimStatus.CONFIRMED,
            confidence=1.0,
            owner_id=event.actor_id,
            visibility="project",
            sensitivity=Sensitivity.PRIVATE,
            allowed_contexts=(f"project:{event.project_id}",),
            excerpt=reason,
            extractor="experiment-outcome-projector",
        )
        if reason:
            self._insert_claim(
                connection,
                event=event,
                claim_id=f"claim:preference:{event.id}",
                subject_type="person",
                subject_id=subject_id,
                predicate="preferred_experiment_result",
                value={"version_id": version_id, "reason": reason},
                context_type="project",
                context_id=event.project_id,
                claim_type=ClaimType.PREFERENCE,
                tags=tags,
                status=ClaimStatus.PROPOSED,
                confidence=0.5,
                owner_id=subject_id,
                visibility="private",
                sensitivity=Sensitivity.PRIVATE,
                allowed_contexts=(f"project:{event.project_id}",),
                excerpt=reason,
                extractor="experiment-outcome-projector",
            )
        self._upsert_project_state(
            connection,
            project_id=event.project_id,
            key="active_version",
            value=version_id,
            event=event,
        )
        self._upsert_project_state(
            connection,
            project_id=event.project_id,
            key="last_experiment",
            value={"experiment_id": experiment_id, "reason": reason},
            event=event,
        )
        if learning_focus:
            self._upsert_learning_state(
                connection,
                subject_id=subject_id,
                project_id=event.project_id,
                focus=learning_focus,
                status="practicing",
                mastery=0.25 if reason else 0.1,
                source_event_id=event.id,
                updated_at=event.occurred_at,
            )

    def _insert_observation(
        self,
        connection: sqlite3.Connection,
        event: MemoryEvent,
        *,
        observation_id: str,
        subject: str,
        event_text: str,
        context: str | None,
        confidence: float,
    ) -> None:
        self._validate_confidence(confidence)
        connection.execute(
            """INSERT INTO observations
               (id, source_event_id, subject, event_text, context, confidence,
                observed_at, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                observation_id,
                event.id,
                subject,
                event_text,
                context,
                confidence,
                event.occurred_at,
                event.project_id,
            ),
        )

    def _insert_claim(
        self,
        connection: sqlite3.Connection,
        *,
        event: MemoryEvent,
        claim_id: str,
        subject_type: str,
        subject_id: str,
        predicate: str,
        value: JsonObject,
        context_type: str | None,
        context_id: str | None,
        claim_type: ClaimType,
        tags: tuple[str, ...],
        status: ClaimStatus,
        confidence: float,
        owner_id: str,
        visibility: str,
        sensitivity: Sensitivity,
        allowed_contexts: tuple[str, ...],
        excerpt: str | None,
        extractor: str,
    ) -> None:
        self._validate_confidence(confidence)
        connection.execute(
            """INSERT INTO claims
               (id, subject_type, subject_id, predicate, value_json, context_type,
                context_id, claim_type, tags_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                claim_id,
                subject_type,
                subject_id,
                predicate,
                _json_dump(value),
                context_type,
                context_id,
                claim_type.value,
                _json_dump(list(tags)),
            ),
        )
        connection.execute(
            """INSERT INTO claim_evidence
               (claim_id, event_id, excerpt, extractor, weight, observed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (claim_id, event.id, excerpt, extractor, confidence, event.occurred_at),
        )
        connection.execute(
            """INSERT INTO claim_states
               (claim_id, status, confidence, valid_from, valid_until,
                superseded_by, last_confirmed_at)
               VALUES (?, ?, ?, ?, NULL, NULL, ?)""",
            (
                claim_id,
                status.value,
                confidence,
                event.occurred_at,
                event.occurred_at if status is ClaimStatus.CONFIRMED else None,
            ),
        )
        connection.execute(
            """INSERT INTO memory_policies
               (claim_id, owner_id, visibility, sensitivity, allowed_contexts_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                claim_id,
                owner_id,
                visibility,
                sensitivity.value,
                _json_dump(list(allowed_contexts)),
            ),
        )

    @staticmethod
    def _upsert_project_state(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        key: str,
        value: JsonValue,
        event: MemoryEvent,
    ) -> None:
        connection.execute(
            """INSERT INTO project_state
               (project_id, state_key, value_json, source_event_id, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(project_id, state_key) DO UPDATE SET
                 value_json = excluded.value_json,
                 source_event_id = excluded.source_event_id,
                 updated_at = excluded.updated_at""",
            (project_id, key, _json_dump(value), event.id, event.occurred_at),
        )

    @staticmethod
    def _upsert_learning_state(
        connection: sqlite3.Connection,
        *,
        subject_id: str,
        project_id: str | None,
        focus: str,
        status: str,
        mastery: float,
        source_event_id: str,
        updated_at: str,
    ) -> None:
        project_key = project_id or ""
        connection.execute(
            """INSERT INTO learning_state
               (subject_id, project_key, focus, status, mastery, evidence_count,
                source_event_id, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(subject_id, project_key, focus) DO UPDATE SET
                 status = excluded.status,
                 mastery = excluded.mastery,
                 evidence_count = learning_state.evidence_count + 1,
                 source_event_id = excluded.source_event_id,
                 updated_at = excluded.updated_at""",
            (
                subject_id,
                project_key,
                focus,
                status,
                mastery,
                source_event_id,
                updated_at,
            ),
        )

    # -- projection reads ------------------------------------------------ #
    def get_observation(self, observation_id: str) -> Observation:
        row = self._connection.execute(
            "SELECT * FROM observations WHERE id = ?", (observation_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"observation not found: {observation_id}")
        return self._observation_from_row(row)

    def list_observations(self, *, project_id: str | None = None) -> list[Observation]:
        if project_id is None:
            rows = self._connection.execute(
                "SELECT * FROM observations ORDER BY observed_at DESC, id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                """SELECT * FROM observations WHERE project_id = ?
                   ORDER BY observed_at DESC, id""",
                (project_id,),
            ).fetchall()
        return [self._observation_from_row(row) for row in rows]

    @staticmethod
    def _observation_from_row(row: sqlite3.Row) -> Observation:
        return Observation(
            id=cast(str, row["id"]),
            source_event_id=cast(str, row["source_event_id"]),
            subject=cast(str, row["subject"]),
            event=cast(str, row["event_text"]),
            context=cast(str | None, row["context"]),
            confidence=float(row["confidence"]),
            observed_at=cast(str, row["observed_at"]),
            project_id=cast(str | None, row["project_id"]),
        )

    def get_claim(self, claim_id: str) -> tuple[MemoryClaim, ClaimState, MemoryPolicy]:
        row = self._connection.execute(
            """SELECT c.*, s.status, s.confidence, s.valid_from, s.valid_until,
                      s.superseded_by, s.last_confirmed_at,
                      p.owner_id, p.visibility, p.sensitivity, p.allowed_contexts_json
               FROM claims c
               JOIN claim_states s ON s.claim_id = c.id
               JOIN memory_policies p ON p.claim_id = c.id
               WHERE c.id = ?""",
            (claim_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"claim not found: {claim_id}")
        tags_value = _json_value(cast(str, row["tags_json"]))
        contexts_value = _json_value(cast(str, row["allowed_contexts_json"]))
        if not isinstance(tags_value, list) or not isinstance(contexts_value, list):
            raise ValueError("stored claim tags or policy contexts are invalid")
        tags = tuple(cast(list[str], tags_value))
        contexts = tuple(cast(list[str], contexts_value))
        claim = MemoryClaim(
            id=cast(str, row["id"]),
            subject_type=cast(str, row["subject_type"]),
            subject_id=cast(str, row["subject_id"]),
            predicate=cast(str, row["predicate"]),
            value=_json_object(cast(str, row["value_json"])),
            context_type=cast(str | None, row["context_type"]),
            context_id=cast(str | None, row["context_id"]),
            claim_type=ClaimType(cast(str, row["claim_type"])),
            tags=tags,
        )
        state = ClaimState(
            claim_id=claim.id,
            status=ClaimStatus(cast(str, row["status"])),
            confidence=float(row["confidence"]),
            valid_from=cast(str | None, row["valid_from"]),
            valid_until=cast(str | None, row["valid_until"]),
            superseded_by=cast(str | None, row["superseded_by"]),
            last_confirmed_at=cast(str | None, row["last_confirmed_at"]),
        )
        policy = MemoryPolicy(
            claim_id=claim.id,
            owner_id=cast(str, row["owner_id"]),
            visibility=cast(str, row["visibility"]),
            sensitivity=Sensitivity(cast(str, row["sensitivity"])),
            allowed_contexts=contexts,
        )
        return claim, state, policy

    def list_claims(
        self,
        *,
        subject_id: str | None = None,
        claim_type: ClaimType | None = None,
        status: ClaimStatus | None = None,
        context_id: str | None = None,
    ) -> list[tuple[MemoryClaim, ClaimState, MemoryPolicy]]:
        clauses: list[str] = []
        params: list[str] = []
        if subject_id is not None:
            clauses.append("c.subject_id = ?")
            params.append(subject_id)
        if claim_type is not None:
            clauses.append("c.claim_type = ?")
            params.append(claim_type.value)
        if status is not None:
            clauses.append("s.status = ?")
            params.append(status.value)
        if context_id is not None:
            clauses.append("c.context_id = ?")
            params.append(context_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._connection.execute(
            f"""SELECT c.id FROM claims c
                 JOIN claim_states s ON s.claim_id = c.id
                 {where} ORDER BY c.rowid DESC""",  # noqa: S608 -- fixed clauses only
            params,
        ).fetchall()
        return [self.get_claim(cast(str, row["id"])) for row in rows]

    def list_project_state(self, project_id: str) -> list[ProjectStateEntry]:
        rows = self._connection.execute(
            """SELECT * FROM project_state WHERE project_id = ?
               ORDER BY state_key""",
            (project_id,),
        ).fetchall()
        return [
            ProjectStateEntry(
                project_id=cast(str, row["project_id"]),
                key=cast(str, row["state_key"]),
                value=_json_value(cast(str, row["value_json"])),
                source_event_id=cast(str, row["source_event_id"]),
                updated_at=cast(str, row["updated_at"]),
            )
            for row in rows
        ]

    def get_learning_state(
        self, subject_id: str, focus: str, *, project_id: str | None
    ) -> LearningState:
        row = self._connection.execute(
            """SELECT * FROM learning_state
               WHERE subject_id = ? AND project_key = ? AND focus = ?""",
            (subject_id, project_id or "", focus),
        ).fetchone()
        if row is None:
            raise KeyError(f"learning state not found: {subject_id}/{focus}")
        return self._learning_from_row(row)

    def list_learning_state(
        self, *, subject_id: str, project_id: str | None = None
    ) -> list[LearningState]:
        if project_id is None:
            rows = self._connection.execute(
                """SELECT * FROM learning_state WHERE subject_id = ?
                   ORDER BY updated_at DESC, focus""",
                (subject_id,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """SELECT * FROM learning_state
                   WHERE subject_id = ? AND project_key = ?
                   ORDER BY updated_at DESC, focus""",
                (subject_id, project_id),
            ).fetchall()
        return [self._learning_from_row(row) for row in rows]

    @staticmethod
    def _learning_from_row(row: sqlite3.Row) -> LearningState:
        project_key = cast(str, row["project_key"])
        return LearningState(
            subject_id=cast(str, row["subject_id"]),
            project_id=project_key or None,
            focus=cast(str, row["focus"]),
            status=cast(str, row["status"]),
            mastery=float(row["mastery"]),
            evidence_count=int(row["evidence_count"]),
            source_event_id=cast(str, row["source_event_id"]),
            updated_at=cast(str, row["updated_at"]),
        )

    def projection_counts(self) -> dict[str, int]:
        """Stable projection summary used by health/debug and replay tests."""
        tables = (
            "observations",
            "claims",
            "claim_evidence",
            "claim_states",
            "memory_policies",
            "project_state",
            "learning_state",
        )
        return {
            table: int(
                self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in tables
        }


__all__ = ["SQLiteMemoryStore"]
