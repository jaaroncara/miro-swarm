"""
Graph storage abstraction and concrete backends.
"""

from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, Optional

from flask import current_app

from ..utils.logger import get_logger

try:
    import kuzu
except ImportError:  # pragma: no cover - dependency availability is environment specific
    kuzu = None


logger = get_logger("mirofish.graph_storage")

# ---- Module-level KuzuDBStorage cache ----
# KuzuDB only supports a single kuzu.Database per directory path.
# This cache ensures we reuse instances across threads and requests.
_kuzu_cache: Dict[str, "KuzuDBStorage"] = {}
_kuzu_cache_lock = threading.Lock()


def get_cached_kuzu_storage(db_path: str) -> "KuzuDBStorage":
    """Return a cached KuzuDBStorage for the given path, creating one if needed."""
    abs_path = os.path.abspath(db_path)
    with _kuzu_cache_lock:
        if abs_path in _kuzu_cache:
            return _kuzu_cache[abs_path]
    # Create outside lock to avoid holding it during slow I/O
    storage = KuzuDBStorage.__new__(KuzuDBStorage)
    storage._init_from_cache(abs_path)
    with _kuzu_cache_lock:
        # Double-check: another thread may have created it while we were init'ing
        if abs_path in _kuzu_cache:
            return _kuzu_cache[abs_path]
        _kuzu_cache[abs_path] = storage
    return storage


class StorageError(RuntimeError):
    """Raised when a graph storage operation fails."""


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _parse_json_dict(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [value]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    return [str(value)]


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _node_payload(node: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(node.get("id", "")),
        "name": str(node.get("name", "")).strip(),
        "label": str(node.get("label", "Entity") or "Entity"),
        "summary": str(node.get("summary", "") or ""),
        "facts": _parse_json_list(node.get("facts", [])),
        "attributes": node.get("attributes") if isinstance(node.get("attributes"), dict) else _parse_json_dict(node.get("attributes")),
        "created_at": str(node.get("created_at", "") or ""),
        "updated_at": str(node.get("updated_at", "") or node.get("created_at", "") or ""),
    }


def _edge_payload(edge: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(edge.get("id", "")),
        "source_id": str(edge.get("source_id", "")),
        "target_id": str(edge.get("target_id", "")),
        "relation": str(edge.get("relation", "")).strip(),
        "weight": float(edge.get("weight", 1.0) or 0.0),
        "fact": str(edge.get("fact", "") or ""),
        "attributes": edge.get("attributes") if isinstance(edge.get("attributes"), dict) else _parse_json_dict(edge.get("attributes")),
        "created_at": str(edge.get("created_at", "") or ""),
        "valid_at": edge.get("valid_at"),
        "invalid_at": edge.get("invalid_at"),
        "expired_at": edge.get("expired_at"),
        "episodes": _parse_json_list(edge.get("episodes", [])),
    }


def _episode_payload(episode: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(episode.get("id", "")),
        "content": str(episode.get("content", "") or ""),
        "source": str(episode.get("source", "document") or "document"),
        "node_ids": _parse_json_list(episode.get("node_ids", [])),
        "processed": _parse_bool(episode.get("processed", False)),
        "created_at": str(episode.get("created_at", "") or ""),
    }


class GraphStorage(ABC):
    @abstractmethod
    def add_node(self, node: dict) -> str:
        ...

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def get_node_by_name(self, name: str) -> Optional[dict]:
        ...

    @abstractmethod
    def update_node(self, node_id: str, updates: dict) -> bool:
        ...

    @abstractmethod
    def delete_node(self, node_id: str) -> bool:
        ...

    @abstractmethod
    def list_nodes(self, label: Optional[str] = None) -> list[dict]:
        ...

    @abstractmethod
    def add_edge(self, edge: dict) -> str:
        ...

    @abstractmethod
    def delete_edge(self, edge_id: str) -> bool:
        ...

    @abstractmethod
    def update_edge(self, edge_id: str, updates: dict) -> bool:
        ...

    @abstractmethod
    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> list[dict]:
        ...

    @abstractmethod
    def add_episode(self, episode: dict) -> str:
        ...

    @abstractmethod
    def get_unprocessed_episodes(self) -> list[dict]:
        ...

    @abstractmethod
    def mark_episode_processed(self, episode_id: str) -> bool:
        ...

    @abstractmethod
    def search_nodes(self, query: str, label: Optional[str] = None, limit: int = 10) -> list[dict]:
        ...

    @abstractmethod
    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict]:
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        ...

    @abstractmethod
    def close(self) -> None:
        ...


class KuzuDBStorage(GraphStorage):
    """Embedded KuzuDB-backed graph storage."""

    def __init__(self, db_path: str):
        """Use get_cached_kuzu_storage() instead of calling this directly."""
        self._init_from_cache(os.path.abspath(db_path))

    def _init_from_cache(self, abs_db_path: str):
        """Internal initializer for both __init__ and cache factory."""
        if kuzu is None:
            message = (
                "Failed to initialize KuzuDB storage: kuzu package is not installed. "
                "Install backend dependencies with `uv sync`."
            )
            logger.error(message)
            raise RuntimeError(message)

        self.db_path = abs_db_path
        self._database_path = os.path.join(self.db_path, "graph.kuzu")
        os.makedirs(self.db_path, exist_ok=True)

        # Retry logic for transient file-lock failures (e.g. cloud-sync agents
        # like OneDrive's fileproviderd holding an fd on the .kuzu file).
        import time

        max_attempts = 5
        retry_delay = 1.0  # seconds, doubles each attempt
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                self._database = kuzu.Database(self._database_path)
                self._connection = kuzu.Connection(self._database)
                self._initialize_schema()
                if attempt > 1:
                    logger.info(
                        "KuzuDB lock acquired on attempt %d at %s",
                        attempt,
                        self._database_path,
                    )
                return  # success
            except Exception as exc:
                last_exc = exc
                is_lock_error = "lock" in str(exc).lower()
                if is_lock_error and attempt < max_attempts:
                    logger.warning(
                        "KuzuDB lock contention at %s (attempt %d/%d), retrying in %.1fs: %s",
                        self._database_path,
                        attempt,
                        max_attempts,
                        retry_delay,
                        exc,
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    break

        logger.error("Failed to initialize KuzuDB storage at %s: %s", self._database_path, last_exc)
        raise RuntimeError(f"Failed to initialize KuzuDB storage at {self.db_path}: {last_exc}") from last_exc

    def _execute(self, query: str, params: Optional[Dict[str, Any]] = None):
        try:
            return self._connection.execute(query, params or {})
        except Exception as exc:
            logger.error("KuzuDB query failed at %s: %s", self._database_path, exc)
            raise StorageError(str(exc)) from exc

    def _initialize_schema(self) -> None:
        self._execute(
            """
            CREATE NODE TABLE IF NOT EXISTS Node(
                id STRING,
                name STRING,
                label STRING,
                summary STRING,
                facts STRING,
                attributes STRING,
                created_at STRING,
                updated_at STRING,
                PRIMARY KEY(id)
            )
            """
        )
        self._execute(
            """
            CREATE NODE TABLE IF NOT EXISTS Episode(
                id STRING,
                content STRING,
                source STRING,
                node_ids STRING,
                processed BOOLEAN,
                created_at STRING,
                PRIMARY KEY(id)
            )
            """
        )
        self._execute(
            """
            CREATE NODE TABLE IF NOT EXISTS Metadata(
                key STRING,
                value STRING,
                updated_at STRING,
                PRIMARY KEY(key)
            )
            """
        )
        self._execute(
            """
            CREATE REL TABLE IF NOT EXISTS RELATES_TO(
                FROM Node TO Node,
                id STRING,
                relation STRING,
                weight DOUBLE,
                fact STRING,
                attributes STRING,
                created_at STRING,
                valid_at STRING,
                invalid_at STRING,
                expired_at STRING,
                episodes STRING
            )
            """
        )
        self._initialize_indexes()

    def _initialize_indexes(self) -> None:
        try:
            self._execute("INSTALL FTS")
            self._execute("LOAD FTS")
            existing = {
                row[1]
                for row in self._execute("CALL SHOW_INDEXES() RETURN *").get_all()
                if len(row) > 1
            }
            indexes = (
                ("Node", "node_lookup_idx", ["name", "label", "summary"]),
                ("Node", "node_time_idx", ["created_at", "updated_at"]),
                ("Episode", "episode_lookup_idx", ["source", "created_at", "content"]),
            )
            for table, index_name, columns in indexes:
                if index_name in existing:
                    continue
                column_list = ", ".join(f"'{column}'" for column in columns)
                self._execute(
                    f"CALL CREATE_FTS_INDEX('{table}', '{index_name}', [{column_list}])"
                )
        except StorageError as exc:
            logger.warning("Skipping optional KuzuDB FTS index setup at %s: %s", self._database_path, exc)

    def _row_to_node(self, row: list[Any]) -> dict:
        return {
            "id": row[0],
            "name": row[1] or "",
            "label": row[2] or "Entity",
            "summary": row[3] or "",
            "facts": _parse_json_list(row[4]),
            "attributes": _parse_json_dict(row[5]),
            "created_at": row[6] or "",
            "updated_at": row[7] or "",
        }

    def _row_to_edge(self, row: list[Any]) -> dict:
        return {
            "id": row[0],
            "relation": row[1] or "",
            "weight": float(row[2] or 0.0),
            "fact": row[3] or "",
            "source_id": row[4] or "",
            "target_id": row[5] or "",
            "attributes": _parse_json_dict(row[6]),
            "created_at": row[7] or "",
            "valid_at": row[8] or None,
            "invalid_at": row[9] or None,
            "expired_at": row[10] or None,
            "episodes": _parse_json_list(row[11]),
        }

    def _row_to_episode(self, row: list[Any]) -> dict:
        return {
            "id": row[0],
            "content": row[1] or "",
            "source": row[2] or "document",
            "node_ids": _parse_json_list(row[3]),
            "processed": bool(row[4]),
            "created_at": row[5] or "",
        }

    def add_node(self, node: dict) -> str:
        payload = _node_payload(node)
        existing = self.get_node_by_name(payload["name"])
        if existing:
            merged_facts = list(dict.fromkeys(existing.get("facts", []) + payload["facts"]))
            merged_attributes = {**existing.get("attributes", {}), **payload["attributes"]}
            updated = {
                "name": payload["name"] or existing["name"],
                "label": payload["label"] or existing["label"],
                "summary": payload["summary"] or existing.get("summary", ""),
                "facts": merged_facts,
                "attributes": merged_attributes,
                "updated_at": payload["updated_at"] or existing.get("updated_at", ""),
            }
            self.update_node(existing["id"], updated)
            return existing["id"]

        self._execute(
            """
            CREATE (n:Node {
                id: $id,
                name: $name,
                label: $label,
                summary: $summary,
                facts: $facts,
                attributes: $attributes,
                created_at: $created_at,
                updated_at: $updated_at
            })
            """,
            {
                "id": payload["id"],
                "name": payload["name"],
                "label": payload["label"],
                "summary": payload["summary"],
                "facts": _json_dumps(payload["facts"]),
                "attributes": _json_dumps(payload["attributes"]),
                "created_at": payload["created_at"],
                "updated_at": payload["updated_at"],
            },
        )
        return payload["id"]

    def get_node(self, node_id: str) -> Optional[dict]:
        rows = self._execute(
            """
            MATCH (n:Node {id: $id})
            RETURN n.id, n.name, n.label, n.summary, n.facts, n.attributes, n.created_at, n.updated_at
            LIMIT 1
            """,
            {"id": node_id},
        ).get_all()
        return self._row_to_node(rows[0]) if rows else None

    def get_node_by_name(self, name: str) -> Optional[dict]:
        rows = self._execute(
            """
            MATCH (n:Node)
            WHERE lower(n.name) = lower($name)
            RETURN n.id, n.name, n.label, n.summary, n.facts, n.attributes, n.created_at, n.updated_at
            LIMIT 1
            """,
            {"name": name.strip()},
        ).get_all()
        return self._row_to_node(rows[0]) if rows else None

    def update_node(self, node_id: str, updates: dict) -> bool:
        existing = self.get_node(node_id)
        if not existing:
            return False

        merged = {**existing, **_node_payload({**existing, **updates})}
        self._execute(
            """
            MATCH (n:Node {id: $id})
            SET n.name = $name,
                n.label = $label,
                n.summary = $summary,
                n.facts = $facts,
                n.attributes = $attributes,
                n.updated_at = $updated_at
            """,
            {
                "id": node_id,
                "name": merged["name"],
                "label": merged["label"],
                "summary": merged["summary"],
                "facts": _json_dumps(merged["facts"]),
                "attributes": _json_dumps(merged["attributes"]),
                "updated_at": merged["updated_at"],
            },
        )
        return True

    def delete_node(self, node_id: str) -> bool:
        if not self.get_node(node_id):
            return False
        self._execute(
            """
            MATCH (a:Node)-[e:RELATES_TO]->(b:Node)
            WHERE a.id = $node_id OR b.id = $node_id
            DELETE e
            """,
            {"node_id": node_id},
        )
        self._execute(
            """
            MATCH (n:Node {id: $id})
            DELETE n
            """,
            {"id": node_id},
        )
        return True

    def list_nodes(self, label: Optional[str] = None) -> list[dict]:
        rows = self._execute(
            """
            MATCH (n:Node)
            RETURN n.id, n.name, n.label, n.summary, n.facts, n.attributes, n.created_at, n.updated_at
            ORDER BY n.name
            """
        ).get_all()
        nodes = [self._row_to_node(row) for row in rows]
        if label:
            return [node for node in nodes if node.get("label") == label]
        return nodes

    def add_edge(self, edge: dict) -> str:
        payload = _edge_payload(edge)
        if not self.get_node(payload["source_id"]) or not self.get_node(payload["target_id"]):
            raise StorageError(
                f"Edge {payload['id']} references missing nodes: "
                f"{payload['source_id']} -> {payload['target_id']}"
            )

        self._execute(
            """
            MATCH (a:Node {id: $source_id}), (b:Node {id: $target_id})
            CREATE (a)-[:RELATES_TO {
                id: $id,
                relation: $relation,
                weight: $weight,
                fact: $fact,
                attributes: $attributes,
                created_at: $created_at,
                valid_at: $valid_at,
                invalid_at: $invalid_at,
                expired_at: $expired_at,
                episodes: $episodes
            }]->(b)
            """,
            {
                "source_id": payload["source_id"],
                "target_id": payload["target_id"],
                "id": payload["id"],
                "relation": payload["relation"],
                "weight": payload["weight"],
                "fact": payload["fact"],
                "attributes": _json_dumps(payload["attributes"]),
                "created_at": payload["created_at"],
                "valid_at": payload["valid_at"] or "",
                "invalid_at": payload["invalid_at"] or "",
                "expired_at": payload["expired_at"] or "",
                "episodes": _json_dumps(payload["episodes"]),
            },
        )
        return payload["id"]

    def delete_edge(self, edge_id: str) -> bool:
        edges = self.get_edges()
        target_edge = next((e for e in edges if e["id"] == edge_id), None)
        if not target_edge:
            return False
            
        self._execute(
            """
            MATCH (a:Node)-[e:RELATES_TO {id: $id}]->(b:Node)
            DELETE e
            """,
            {"id": edge_id},
        )
        return True

    def update_edge(self, edge_id: str, updates: dict) -> bool:
        edges = self.get_edges()
        existing = next((e for e in edges if e["id"] == edge_id), None)
        if not existing:
            return False

        merged = {**existing, **updates}
        
        # If the relation type is being explicitly changed, we might need a delete + recreate pattern
        # KuzuDB RELATES_TO is a single generic edge table that stores 'relation' as a property
        self._execute(
            """
            MATCH (a:Node)-[e:RELATES_TO {id: $id}]->(b:Node)
            SET e.relation = $relation,
                e.weight = $weight,
                e.fact = $fact,
                e.attributes = $attributes,
                e.valid_at = $valid_at,
                e.invalid_at = $invalid_at,
                e.expired_at = $expired_at,
                e.episodes = $episodes
            """,
            {
                "id": edge_id,
                "relation": merged["relation"],
                "weight": merged["weight"],
                "fact": merged["fact"],
                "attributes": _json_dumps(merged["attributes"]),
                "valid_at": merged["valid_at"] or "",
                "invalid_at": merged["invalid_at"] or "",
                "expired_at": merged["expired_at"] or "",
                "episodes": _json_dumps(merged["episodes"]),
            },
        )
        return True

    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> list[dict]:
        rows = self._execute(
            """
            MATCH (a:Node)-[e:RELATES_TO]->(b:Node)
            RETURN e.id, e.relation, e.weight, e.fact, a.id, b.id, e.attributes,
                   e.created_at, e.valid_at, e.invalid_at, e.expired_at, e.episodes
            """
        ).get_all()
        edges = [self._row_to_edge(row) for row in rows]
        filtered = []
        for edge in edges:
            if source_id and edge["source_id"] != source_id:
                continue
            if target_id and edge["target_id"] != target_id:
                continue
            if relation and edge["relation"] != relation:
                continue
            filtered.append(edge)
        return filtered

    def add_episode(self, episode: dict) -> str:
        payload = _episode_payload(episode)
        self._execute(
            """
            CREATE (e:Episode {
                id: $id,
                content: $content,
                source: $source,
                node_ids: $node_ids,
                processed: $processed,
                created_at: $created_at
            })
            """,
            {
                "id": payload["id"],
                "content": payload["content"],
                "source": payload["source"],
                "node_ids": _json_dumps(payload["node_ids"]),
                "processed": payload["processed"],
                "created_at": payload["created_at"],
            },
        )
        return payload["id"]

    def get_episode(self, episode_id: str) -> Optional[dict]:
        rows = self._execute(
            """
            MATCH (e:Episode {id: $id})
            RETURN e.id, e.content, e.source, e.node_ids, e.processed, e.created_at
            LIMIT 1
            """,
            {"id": episode_id},
        ).get_all()
        return self._row_to_episode(rows[0]) if rows else None

    def get_unprocessed_episodes(self) -> list[dict]:
        rows = self._execute(
            """
            MATCH (e:Episode)
            WHERE e.processed = false
            RETURN e.id, e.content, e.source, e.node_ids, e.processed, e.created_at
            ORDER BY e.created_at
            """
        ).get_all()
        return [self._row_to_episode(row) for row in rows]

    def mark_episode_processed(self, episode_id: str) -> bool:
        if not self.get_episode(episode_id):
            return False
        self._execute(
            """
            MATCH (e:Episode {id: $id})
            SET e.processed = true
            """,
            {"id": episode_id},
        )
        return True

    def search_nodes(self, query: str, label: Optional[str] = None, limit: int = 10) -> list[dict]:
        query_terms = [term for term in query.lower().split() if term]
        scored = []
        for node in self.list_nodes(label=label):
            haystack = " ".join(
                [
                    node.get("name", ""),
                    node.get("label", ""),
                    node.get("summary", ""),
                    " ".join(node.get("facts", [])),
                    _json_dumps(node.get("attributes", {})),
                ]
            ).lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score:
                scored.append((score, node))
        scored.sort(key=lambda item: (-item[0], item[1].get("name", "")))
        return [node for _, node in scored[:limit]]

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict]:
        depth = max(depth, 1)
        seen = {node_id}
        frontier = {node_id}
        neighbors: list[dict] = []

        for _ in range(depth):
            next_frontier = set()
            for current in frontier:
                for edge in self.get_edges(source_id=current):
                    neighbor_id = edge["target_id"]
                    if neighbor_id in seen:
                        continue
                    neighbor = self.get_node(neighbor_id)
                    if neighbor:
                        neighbors.append(neighbor)
                        seen.add(neighbor_id)
                        next_frontier.add(neighbor_id)
                for edge in self.get_edges(target_id=current):
                    neighbor_id = edge["source_id"]
                    if neighbor_id in seen:
                        continue
                    neighbor = self.get_node(neighbor_id)
                    if neighbor:
                        neighbors.append(neighbor)
                        seen.add(neighbor_id)
                        next_frontier.add(neighbor_id)
            frontier = next_frontier
            if not frontier:
                break
        return neighbors

    def get_stats(self) -> dict:
        nodes = self.list_nodes()
        edges = self.get_edges()
        episodes = self._execute(
            """
            MATCH (e:Episode)
            RETURN e.id, e.content, e.source, e.node_ids, e.processed, e.created_at
            """
        ).get_all()
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "episode_count": len(episodes),
            "unprocessed_episode_count": len(self.get_unprocessed_episodes()),
        }

    def set_metadata(self, key: str, value: Any, updated_at: str) -> None:
        existing = self.get_metadata(key)
        encoded = _json_dumps(value)
        if existing is None:
            self._execute(
                """
                CREATE (m:Metadata {key: $key, value: $value, updated_at: $updated_at})
                """,
                {"key": key, "value": encoded, "updated_at": updated_at},
            )
            return
        self._execute(
            """
            MATCH (m:Metadata {key: $key})
            SET m.value = $value,
                m.updated_at = $updated_at
            """,
            {"key": key, "value": encoded, "updated_at": updated_at},
        )

    def get_metadata(self, key: str) -> Any:
        rows = self._execute(
            """
            MATCH (m:Metadata {key: $key})
            RETURN m.value
            LIMIT 1
            """,
            {"key": key},
        ).get_all()
        if not rows:
            return None
        value = rows[0][0]
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    def close(self) -> None:
        if self._connection:
            self._connection.close()
        if self._database:
            self._database.close()
        self._connection = None
        self._database = None


class JSONStorage(GraphStorage):
    """JSON-file fallback storage."""

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

    @property
    def _nodes_path(self) -> str:
        return os.path.join(self.data_dir, "nodes.json")

    @property
    def _edges_path(self) -> str:
        return os.path.join(self.data_dir, "edges.json")

    @property
    def _episodes_path(self) -> str:
        return os.path.join(self.data_dir, "episodes.json")

    @property
    def _metadata_path(self) -> str:
        return os.path.join(self.data_dir, "metadata.json")

    def _load_json(self, path: str, default: Any) -> Any:
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _save_json(self, path: str, value: Any) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)

    def _load_nodes(self) -> list[dict]:
        return [_node_payload(node) for node in self._load_json(self._nodes_path, [])]

    def _save_nodes(self, nodes: Iterable[dict]) -> None:
        self._save_json(self._nodes_path, list(nodes))

    def _load_edges(self) -> list[dict]:
        return [_edge_payload(edge) for edge in self._load_json(self._edges_path, [])]

    def _save_edges(self, edges: Iterable[dict]) -> None:
        self._save_json(self._edges_path, list(edges))

    def _load_episodes(self) -> list[dict]:
        return [_episode_payload(episode) for episode in self._load_json(self._episodes_path, [])]

    def _save_episodes(self, episodes: Iterable[dict]) -> None:
        self._save_json(self._episodes_path, list(episodes))

    def add_node(self, node: dict) -> str:
        payload = _node_payload(node)
        nodes = self._load_nodes()
        for index, existing in enumerate(nodes):
            if existing["name"].lower() == payload["name"].lower():
                merged = {
                    **existing,
                    **payload,
                    "facts": list(dict.fromkeys(existing.get("facts", []) + payload["facts"])),
                    "attributes": {**existing.get("attributes", {}), **payload["attributes"]},
                    "summary": payload["summary"] or existing.get("summary", ""),
                    "label": payload["label"] or existing.get("label", "Entity"),
                }
                nodes[index] = merged
                self._save_nodes(nodes)
                return existing["id"]
        nodes.append(payload)
        self._save_nodes(nodes)
        return payload["id"]

    def get_node(self, node_id: str) -> Optional[dict]:
        for node in self._load_nodes():
            if node["id"] == node_id:
                return node
        return None

    def get_node_by_name(self, name: str) -> Optional[dict]:
        normalized = name.strip().lower()
        for node in self._load_nodes():
            if node["name"].lower() == normalized:
                return node
        return None

    def update_node(self, node_id: str, updates: dict) -> bool:
        nodes = self._load_nodes()
        for index, existing in enumerate(nodes):
            if existing["id"] != node_id:
                continue
            nodes[index] = {**existing, **_node_payload({**existing, **updates})}
            self._save_nodes(nodes)
            return True
        return False

    def delete_node(self, node_id: str) -> bool:
        nodes = self._load_nodes()
        filtered_nodes = [node for node in nodes if node["id"] != node_id]
        if len(filtered_nodes) == len(nodes):
            return False
        self._save_nodes(filtered_nodes)
        self._save_edges(
            [
                edge
                for edge in self._load_edges()
                if edge["source_id"] != node_id and edge["target_id"] != node_id
            ]
        )
        return True

    def list_nodes(self, label: Optional[str] = None) -> list[dict]:
        nodes = sorted(self._load_nodes(), key=lambda item: item.get("name", ""))
        if label:
            return [node for node in nodes if node.get("label") == label]
        return nodes

    def add_edge(self, edge: dict) -> str:
        payload = _edge_payload(edge)
        if not self.get_node(payload["source_id"]) or not self.get_node(payload["target_id"]):
            raise StorageError(
                f"Edge {payload['id']} references missing nodes: "
                f"{payload['source_id']} -> {payload['target_id']}"
            )
        edges = self._load_edges()
        edges.append(payload)
        self._save_edges(edges)
        return payload["id"]

    def delete_edge(self, edge_id: str) -> bool:
        edges = self._load_edges()
        filtered = [e for e in edges if e["id"] != edge_id]
        if len(filtered) == len(edges):
            return False
        self._save_edges(filtered)
        return True

    def update_edge(self, edge_id: str, updates: dict) -> bool:
        edges = self._load_edges()
        for idx, e in enumerate(edges):
            if e["id"] == edge_id:
                edges[idx] = {**e, **updates}
                self._save_edges(edges)
                return True
        return False

    def get_edges(
        self,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        relation: Optional[str] = None,
    ) -> list[dict]:
        edges = self._load_edges()
        filtered = []
        for edge in edges:
            if source_id and edge["source_id"] != source_id:
                continue
            if target_id and edge["target_id"] != target_id:
                continue
            if relation and edge["relation"] != relation:
                continue
            filtered.append(edge)
        return filtered

    def add_episode(self, episode: dict) -> str:
        payload = _episode_payload(episode)
        episodes = self._load_episodes()
        episodes.append(payload)
        self._save_episodes(episodes)
        return payload["id"]

    def get_episode(self, episode_id: str) -> Optional[dict]:
        for episode in self._load_episodes():
            if episode["id"] == episode_id:
                return episode
        return None

    def get_unprocessed_episodes(self) -> list[dict]:
        return [episode for episode in self._load_episodes() if not episode.get("processed", False)]

    def mark_episode_processed(self, episode_id: str) -> bool:
        episodes = self._load_episodes()
        for index, episode in enumerate(episodes):
            if episode["id"] != episode_id:
                continue
            updated = dict(episode)
            updated["processed"] = True
            episodes[index] = updated
            self._save_episodes(episodes)
            return True
        return False

    def search_nodes(self, query: str, label: Optional[str] = None, limit: int = 10) -> list[dict]:
        query_terms = [term for term in query.lower().split() if term]
        scored = []
        for node in self.list_nodes(label=label):
            haystack = " ".join(
                [
                    node.get("name", ""),
                    node.get("label", ""),
                    node.get("summary", ""),
                    " ".join(node.get("facts", [])),
                    _json_dumps(node.get("attributes", {})),
                ]
            ).lower()
            score = sum(1 for term in query_terms if term in haystack)
            if score:
                scored.append((score, node))
        scored.sort(key=lambda item: (-item[0], item[1].get("name", "")))
        return [node for _, node in scored[:limit]]

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict]:
        depth = max(depth, 1)
        seen = {node_id}
        frontier = {node_id}
        neighbors: list[dict] = []
        for _ in range(depth):
            next_frontier = set()
            for current in frontier:
                for edge in self.get_edges(source_id=current):
                    neighbor = self.get_node(edge["target_id"])
                    if neighbor and neighbor["id"] not in seen:
                        seen.add(neighbor["id"])
                        next_frontier.add(neighbor["id"])
                        neighbors.append(neighbor)
                for edge in self.get_edges(target_id=current):
                    neighbor = self.get_node(edge["source_id"])
                    if neighbor and neighbor["id"] not in seen:
                        seen.add(neighbor["id"])
                        next_frontier.add(neighbor["id"])
                        neighbors.append(neighbor)
            frontier = next_frontier
            if not frontier:
                break
        return neighbors

    def get_stats(self) -> dict:
        nodes = self._load_nodes()
        edges = self._load_edges()
        episodes = self._load_episodes()
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "episode_count": len(episodes),
            "unprocessed_episode_count": len([episode for episode in episodes if not episode.get("processed", False)]),
        }

    def set_metadata(self, key: str, value: Any, updated_at: str) -> None:
        metadata = self._load_json(self._metadata_path, {})
        metadata[key] = {
            "value": value,
            "updated_at": updated_at,
        }
        self._save_json(self._metadata_path, metadata)

    def get_metadata(self, key: str) -> Any:
        metadata = self._load_json(self._metadata_path, {})
        entry = metadata.get(key)
        if not entry:
            return None
        return entry.get("value")

    def close(self) -> None:
        return None


def get_app_graph_storage(graph_id: Optional[str] = None) -> Optional[GraphStorage]:
    """Resolve the configured graph storage from the active Flask app."""
    try:
        storage = current_app.extensions.get("graph_storage")
    except RuntimeError:
        return None

    if storage is None or graph_id is None:
        return storage

    if isinstance(storage, KuzuDBStorage):
        return get_cached_kuzu_storage(os.path.join(storage.db_path, graph_id))
    if isinstance(storage, JSONStorage):
        return JSONStorage(os.path.join(storage.data_dir, graph_id))
    return storage
