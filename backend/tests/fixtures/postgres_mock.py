from __future__ import annotations

from collections.abc import Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models.evidence import Evidence, ExplorerFinding, ExplorerNarrative, ExplorerProgress, ExplorerQuote
from app.models.mini import Mini


def _bound_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    return value


def _column_name(column: Any) -> str | None:
    return getattr(column, "name", None) or getattr(column, "key", None)


def _resolve_update_value(value: Any) -> Any:
    resolved = _bound_value(value)
    if resolved is value and "now(" in str(value).lower():
        return datetime.now(timezone.utc)
    return resolved


class _MockScalars:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _MockResult:
    def __init__(self, rows: list[Any], returning: tuple[Any, ...] = ()):
        self._rows = rows
        self._returning = returning

    def scalars(self) -> _MockScalars:
        return _MockScalars(self._rows)

    def scalar_one_or_none(self) -> Any:
        if not self._rows:
            return None
        row = self._rows[0]
        if self._returning:
            col = self._returning[0]
            return getattr(row, _column_name(col) or "", None)
        return row

    def scalar_one(self) -> Any:
        result = self.scalar_one_or_none()
        if result is None:
            raise ValueError("No rows returned")
        return result

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


@dataclass
class _SessionFactoryContext(AbstractAsyncContextManager["PostgresStyleSession"]):
    session: "PostgresStyleSession"

    async def __aenter__(self) -> "PostgresStyleSession":
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class PostgresStyleSession:
    __chief_fanout__ = True

    _TABLE_TO_MODEL: dict[str, type[Any]] = {
        Evidence.__tablename__: Evidence,
        ExplorerFinding.__tablename__: ExplorerFinding,
        ExplorerNarrative.__tablename__: ExplorerNarrative,
        ExplorerProgress.__tablename__: ExplorerProgress,
        ExplorerQuote.__tablename__: ExplorerQuote,
        Mini.__tablename__: Mini,
    }

    def __init__(self, initial_records: Iterable[Any] | None = None):
        self.records: list[Any] = list(initial_records or [])
        self.store: dict[tuple[str, tuple[Any, ...]], Any] = {}

    async def __aenter__(self) -> "PostgresStyleSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def add(self, record: Any) -> None:
        if getattr(record, "id", None) is None:
            record.id = str(uuid4())
        if hasattr(record, "created_at") and getattr(record, "created_at", None) is None:
            record.created_at = datetime.now(timezone.utc)
        self.records.append(record)

    async def commit(self) -> None:
        return None

    async def flush(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def execute(self, stmt: Any) -> _MockResult:
        if hasattr(stmt, "_post_values_clause") and hasattr(stmt, "table"):
            return self._execute_upsert(stmt)
        if stmt.__class__.__name__.lower().endswith("update"):
            return self._execute_update(stmt)
        if hasattr(stmt, "column_descriptions"):
            return self._execute_select(stmt)
        return _MockResult([])

    def _execute_upsert(self, stmt: Any) -> _MockResult:
        table_name = stmt.table.name
        model_cls = self._TABLE_TO_MODEL.get(table_name)
        if model_cls is None:
            raise ValueError(f"Unsupported upsert table: {table_name}")

        values = {(_column_name(col) or ""): _bound_value(val) for col, val in stmt._values.items()}
        conflict_columns = [
            _column_name(col) if not isinstance(col, str) else col
            for col in stmt._post_values_clause.inferred_target_elements
        ]
        key_tuple = tuple(values.get(col or "") for col in conflict_columns)
        store_key = (table_name, key_tuple)
        record = self.store.get(store_key)

        if record is None:
            if "id" not in values or values["id"] is None:
                values["id"] = str(uuid4())
            if hasattr(model_cls, "created_at") and values.get("created_at") is None:
                values["created_at"] = datetime.now(timezone.utc)
            record = model_cls(**values)
            self.records.append(record)
            self.store[store_key] = record

        for key, value in stmt._post_values_clause.update_values_to_set:
            name = _column_name(key) if not isinstance(key, str) else key
            if not name:
                continue
            setattr(record, name, _resolve_update_value(value))

        returning = tuple(getattr(stmt, "_returning", ()) or ())
        return _MockResult([record], returning=returning)

    def _execute_update(self, stmt: Any) -> _MockResult:
        table_name = stmt.table.name
        model_cls = self._TABLE_TO_MODEL.get(table_name)
        if model_cls is None:
            return _MockResult([])

        rows = [row for row in self.records if isinstance(row, model_cls)]
        rows = [row for row in rows if self._matches_all(stmt, row)]
        for row in rows:
            for key, value in stmt._values.items():
                name = _column_name(key) if not isinstance(key, str) else key
                if not name:
                    continue
                if hasattr(value, "left") and hasattr(value, "right"):
                    left_name = _column_name(value.left)
                    if left_name and getattr(value.operator, "__name__", "") == "add":
                        increment = _bound_value(value.right)
                        setattr(row, name, getattr(row, left_name, 0) + increment)
                        continue
                setattr(row, name, _resolve_update_value(value))
        return _MockResult(rows)

    def _execute_select(self, stmt: Any) -> _MockResult:
        entity = stmt.column_descriptions[0].get("entity")
        if entity is None:
            return _MockResult([])

        rows = [row for row in self.records if isinstance(row, entity)]
        rows = [row for row in rows if self._matches_all(stmt, row)]
        rows = self._apply_order_by(stmt, rows)

        limit_clause = getattr(stmt, "_limit_clause", None)
        if limit_clause is not None:
            limit_value = _bound_value(limit_clause)
            if isinstance(limit_value, int):
                rows = rows[:limit_value]

        return _MockResult(rows)

    def _matches_all(self, stmt: Any, row: Any) -> bool:
        criteria = list(getattr(stmt, "_where_criteria", ()) or ())
        return all(self._matches(criterion, row) for criterion in criteria)

    def _matches(self, criterion: Any, row: Any) -> bool:
        if hasattr(criterion, "clauses"):
            op_name = getattr(getattr(criterion, "operator", None), "__name__", "")
            if op_name == "or_":
                return any(self._matches(clause, row) for clause in criterion.clauses)
            return all(self._matches(clause, row) for clause in criterion.clauses)
        if not hasattr(criterion, "left") or not hasattr(criterion, "operator"):
            return True

        left_name = _column_name(criterion.left)
        if not left_name:
            return True
        left_value = getattr(row, left_name, None)
        right_value = _bound_value(getattr(criterion, "right", None))
        op_name = getattr(criterion.operator, "__name__", "")

        if op_name in {"eq", "is_"}:
            return left_value == right_value
        if op_name in {"ne", "is_not"}:
            if right_value is None:
                return left_value is not None
            return left_value != right_value
        if op_name == "ge":
            return left_value is not None and right_value is not None and left_value >= right_value
        if op_name == "gt":
            return left_value is not None and right_value is not None and left_value > right_value
        if op_name == "le":
            return left_value is not None and right_value is not None and left_value <= right_value
        if op_name == "lt":
            return left_value is not None and right_value is not None and left_value < right_value
        return True

    def _apply_order_by(self, stmt: Any, rows: list[Any]) -> list[Any]:
        order_by = list(getattr(stmt, "_order_by_clauses", ()) or ())
        ordered = list(rows)
        for clause in reversed(order_by):
            descending = getattr(getattr(clause, "modifier", None), "__name__", "") == "desc_op"
            column = getattr(clause, "element", clause)
            name = _column_name(column)
            if not name:
                continue
            ordered.sort(
                key=lambda row: (getattr(row, name, None) is None, getattr(row, name, None)),
                reverse=descending,
            )
        return ordered


def make_session_factory(mock_session: PostgresStyleSession):
    def _factory() -> _SessionFactoryContext:
        return _SessionFactoryContext(session=mock_session)

    return _factory
