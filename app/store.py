from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .models import (
    Assumption, AssumptionInput, CognitiveMap, FeedbackRequest, RawItem, RunResult,
    SavedGoal, SourceProfile,
)


class Store:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self._connection() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items (
                item_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1,
                last_score REAL NOT NULL DEFAULT 0,
                last_disposition TEXT NOT NULL DEFAULT 'background'
            );
            CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                goal TEXT NOT NULL,
                raw_count INTEGER NOT NULL,
                filtered_count INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                source TEXT NOT NULL,
                useful INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_source ON feedback(source);
            CREATE TABLE IF NOT EXISTS goals (
                name TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                horizon_hours INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_health (
                source TEXT PRIMARY KEY,
                successes INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,
                last_ok TEXT,
                last_error TEXT,
                last_error_at TEXT
            );
            CREATE TABLE IF NOT EXISTS query_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                purpose TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'goal',
                result_count INTEGER NOT NULL DEFAULT 0,
                ok INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_query_events_category ON query_events(category, created_at);
            CREATE INDEX IF NOT EXISTS idx_query_events_source ON query_events(source, created_at);
            CREATE TABLE IF NOT EXISTS assumptions (
                id TEXT PRIMARY KEY,
                statement TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT .6,
                status TEXT NOT NULL DEFAULT 'active',
                origin TEXT NOT NULL DEFAULT 'user',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_challenged_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS environments (
                environment_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                times_seen INTEGER NOT NULL DEFAULT 1,
                max_distance REAL NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL
            );
            ''')
            self._ensure_column(db, 'items', 'source_category', "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, 'items', 'last_query', "TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})').fetchall()}
        if column not in columns:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')

    def history(self, item_ids: list[str]) -> dict[str, dict]:
        if not item_ids:
            return {}
        placeholders = ','.join('?' for _ in item_ids)
        with self._connection() as db:
            rows = db.execute(
                f'SELECT item_id, first_seen, last_seen, seen_count FROM items WHERE item_id IN ({placeholders})',
                item_ids,
            ).fetchall()
        return {row['item_id']: dict(row) for row in rows}

    def source_weights(self) -> dict[str, float]:
        with self._connection() as db:
            rows = db.execute('''
                SELECT source,
                       SUM(CASE WHEN useful=1 THEN 1 ELSE 0 END) AS good,
                       COUNT(*) AS total
                FROM feedback GROUP BY source
            ''').fetchall()
        weights: dict[str, float] = {}
        for row in rows:
            total = row['total'] or 0
            if total < 3:
                continue
            ratio = row['good'] / total
            weights[row['source']] = max(0.75, min(1.25, 0.75 + 0.5 * ratio))
        return weights

    def record_source_health(self, source: str, ok: bool, error: str = '') -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as db:
            db.execute('INSERT OR IGNORE INTO source_health(source) VALUES(?)', (source,))
            if ok:
                db.execute('UPDATE source_health SET successes=successes+1,last_ok=? WHERE source=?', (now, source))
            else:
                db.execute(
                    'UPDATE source_health SET failures=failures+1,last_error=?,last_error_at=? WHERE source=?',
                    (error[:1000], now, source),
                )

    def observe_items(self, items: list[RawItem]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as db:
            for item in items:
                db.execute('''
                    INSERT INTO items(
                        item_id,source,title,url,first_seen,last_seen,seen_count,last_score,
                        last_disposition,source_category,last_query
                    )
                    VALUES(?,?,?,?,?,?,1,0,'background',?,?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        last_seen=excluded.last_seen, seen_count=items.seen_count+1,
                        title=excluded.title, url=excluded.url,
                        source_category=excluded.source_category, last_query=excluded.last_query
                ''', (
                    item.id, item.source, item.title, item.url, now, now,
                    item.source_category, item.query,
                ))

    def record_query_events(self, run_id: str, events: list[dict]) -> None:
        if not events:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connection() as db:
            for event in events:
                db.execute('''
                    INSERT INTO query_events(
                        run_id,source,category,query,purpose,mode,result_count,ok,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                ''', (
                    run_id, event.get('source', ''), event.get('category', ''),
                    event.get('query', ''), event.get('purpose', ''), event.get('mode', 'goal'),
                    int(event.get('result_count', 0)), int(bool(event.get('ok', True))), now,
                ))

    def coverage(self, days: int = 90) -> list[dict]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).isoformat()
        with self._connection() as db:
            query_rows = db.execute('''
                SELECT category, COUNT(*) AS searches, SUM(result_count) AS results,
                       MAX(created_at) AS last_query
                FROM query_events
                WHERE created_at >= ?
                GROUP BY category
            ''', (cutoff,)).fetchall()
            item_rows = db.execute('''
                SELECT source_category AS category, COUNT(*) AS items, MAX(last_seen) AS last_seen
                FROM items
                WHERE last_seen >= ? AND source_category != ''
                GROUP BY source_category
            ''', (cutoff,)).fetchall()
        merged: dict[str, dict] = {}
        for row in query_rows:
            merged[row['category']] = {
                'category': row['category'], 'searches': row['searches'],
                'results': row['results'] or 0, 'last_query': row['last_query'],
                'items': 0, 'last_seen': None,
            }
        for row in item_rows:
            entry = merged.setdefault(row['category'], {
                'category': row['category'], 'searches': 0, 'results': 0,
                'last_query': None, 'items': 0, 'last_seen': None,
            })
            entry['items'] = row['items']
            entry['last_seen'] = row['last_seen']
        return sorted(merged.values(), key=lambda x: (x['searches'], x['items'], x['category']))

    def cognitive_context(self, profiles: dict[str, SourceProfile]) -> dict:
        coverage = self.coverage(90)
        coverage_map = {row['category']: row for row in coverage}
        categories = sorted({profile.category for profile in profiles.values()})
        underexplored = []
        for category in categories:
            row = coverage_map.get(category)
            if not row:
                underexplored.append({
                    'category': category, 'searches': 0, 'items': 0,
                    'reason': 'No search has been recorded in this source category during the coverage window.',
                })
            elif row['searches'] <= 1 or row['items'] == 0:
                underexplored.append({
                    'category': category, 'searches': row['searches'], 'items': row['items'],
                    'reason': 'This category has little search/observation history.',
                })

        recent_challenges: list[dict] = []
        recent_environments: list[dict] = []
        with self._connection() as db:
            rows = db.execute(
                'SELECT payload_json FROM runs ORDER BY created_at DESC LIMIT 12'
            ).fetchall()
        for row in rows:
            try:
                cognitive = json.loads(row['payload_json']).get('cognitive_map', {})
            except (TypeError, json.JSONDecodeError):
                continue
            recent_challenges.extend(cognitive.get('model_failures', [])[:3])
            recent_environments.extend(cognitive.get('distant_environments', [])[:3])

        return {
            'coverage_window_days': 90,
            'coverage': coverage,
            'underexplored_categories': underexplored[:12],
            'assumptions': [a.model_dump() for a in self.list_assumptions() if a.status != 'retired'][:20],
            'recent_model_challenges': recent_challenges[:12],
            'recent_distant_environments': recent_environments[:12],
        }

    def record_run(self, result: RunResult) -> None:
        now = result.created_at.isoformat()
        payload = result.model_dump_json()
        with self._lock, self._connection() as db:
            db.execute(
                'INSERT OR REPLACE INTO runs(run_id,created_at,goal,raw_count,filtered_count,payload_json) VALUES(?,?,?,?,?,?)',
                (result.run_id, now, result.plan.goal, result.raw_count, result.filtered_count, payload),
            )
            for item in result.items:
                db.execute(
                    'UPDATE items SET last_score=?,last_disposition=? WHERE item_id=?',
                    (item.score, item.disposition, item.id),
                )
            self._record_environments(db, result.cognitive_map, now)
            self._mark_challenges(db, result.cognitive_map, now)

    @staticmethod
    def _record_environments(db: sqlite3.Connection, cognitive: CognitiveMap, now: str) -> None:
        for environment in cognitive.distant_environments:
            key = hashlib.sha256(environment.name.strip().lower().encode('utf-8')).hexdigest()[:20]
            payload = environment.model_dump_json()
            db.execute('''
                INSERT INTO environments(environment_key,name,first_seen,last_seen,times_seen,max_distance,payload_json)
                VALUES(?,?,?,?,1,?,?)
                ON CONFLICT(environment_key) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    times_seen=environments.times_seen+1,
                    max_distance=MAX(environments.max_distance,excluded.max_distance),
                    payload_json=excluded.payload_json
            ''', (key, environment.name, now, now, environment.distance, payload))

    @staticmethod
    def _mark_challenges(db: sqlite3.Connection, cognitive: CognitiveMap, now: str) -> None:
        for challenge in cognitive.model_failures:
            if challenge.assumption_id:
                db.execute(
                    "UPDATE assumptions SET status='challenged',last_challenged_at=?,updated_at=? WHERE id=?",
                    (now, now, challenge.assumption_id),
                )
            else:
                db.execute(
                    "UPDATE assumptions SET status='challenged',last_challenged_at=?,updated_at=? "
                    "WHERE lower(trim(statement))=lower(trim(?))",
                    (now, now, challenge.assumption),
                )

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                'SELECT run_id,created_at,goal,raw_count,filtered_count,payload_json FROM runs ORDER BY created_at DESC LIMIT ?',
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            data = json.loads(row['payload_json'])
            out.append({
                'run_id': row['run_id'], 'created_at': row['created_at'], 'goal': row['goal'],
                'raw_count': row['raw_count'], 'filtered_count': row['filtered_count'],
                'headline': data.get('digest', {}).get('headline', ''),
                'items': len(data.get('items', [])),
                'model_challenges': len(data.get('cognitive_map', {}).get('model_failures', [])),
                'distant_environments': len(data.get('cognitive_map', {}).get('distant_environments', [])),
            })
        return out

    def get_run(self, run_id: str) -> dict | None:
        with self._connection() as db:
            row = db.execute('SELECT payload_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row['payload_json']) if row else None

    def add_feedback(self, feedback: FeedbackRequest) -> None:
        with self._lock, self._connection() as db:
            db.execute(
                'INSERT INTO feedback(item_id,source,useful,note,created_at) VALUES(?,?,?,?,?)',
                (feedback.item_id, feedback.source, int(feedback.useful), feedback.note,
                 datetime.now(timezone.utc).isoformat()),
            )

    def list_goals(self) -> list[SavedGoal]:
        with self._connection() as db:
            rows = db.execute('SELECT name,prompt,horizon_hours,enabled FROM goals ORDER BY name').fetchall()
        return [
            SavedGoal(name=r['name'], prompt=r['prompt'], horizon_hours=r['horizon_hours'], enabled=bool(r['enabled']))
            for r in rows
        ]

    def save_goal(self, goal: SavedGoal) -> None:
        with self._lock, self._connection() as db:
            db.execute('''
                INSERT INTO goals(name,prompt,horizon_hours,enabled,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET prompt=excluded.prompt,horizon_hours=excluded.horizon_hours,
                    enabled=excluded.enabled,updated_at=excluded.updated_at
            ''', (
                goal.name, goal.prompt, goal.horizon_hours, int(goal.enabled),
                datetime.now(timezone.utc).isoformat(),
            ))

    def delete_goal(self, name: str) -> None:
        with self._lock, self._connection() as db:
            db.execute('DELETE FROM goals WHERE name=?', (name,))

    def health(self) -> list[dict]:
        with self._connection() as db:
            rows = db.execute('SELECT * FROM source_health ORDER BY source').fetchall()
        return [dict(r) for r in rows]

    def list_assumptions(self) -> list[Assumption]:
        with self._connection() as db:
            rows = db.execute(
                'SELECT id,statement,scope,confidence,status,origin,created_at,updated_at,last_challenged_at '
                'FROM assumptions ORDER BY updated_at DESC'
            ).fetchall()
        return [Assumption(**dict(row)) for row in rows]

    def save_assumption(self, assumption: AssumptionInput, *, origin: str = 'user') -> Assumption:
        now = datetime.now(timezone.utc).isoformat()
        key_material = f'{assumption.scope.strip().lower()}\0{assumption.statement.strip().lower()}'
        assumption_id = hashlib.sha256(key_material.encode('utf-8')).hexdigest()[:16]
        with self._lock, self._connection() as db:
            db.execute('''
                INSERT INTO assumptions(
                    id,statement,scope,confidence,status,origin,created_at,updated_at,last_challenged_at
                ) VALUES(?,?,?,?,?,?,?,?,'')
                ON CONFLICT(id) DO UPDATE SET
                    statement=excluded.statement,scope=excluded.scope,confidence=excluded.confidence,
                    status='active',origin=excluded.origin,updated_at=excluded.updated_at
            ''', (
                assumption_id, assumption.statement, assumption.scope, assumption.confidence,
                'active', origin, now, now,
            ))
        return next(a for a in self.list_assumptions() if a.id == assumption_id)

    def delete_assumption(self, assumption_id: str) -> None:
        with self._lock, self._connection() as db:
            db.execute('DELETE FROM assumptions WHERE id=?', (assumption_id,))

    def environments(self, limit: int = 50) -> list[dict]:
        with self._connection() as db:
            rows = db.execute(
                'SELECT environment_key,name,first_seen,last_seen,times_seen,max_distance,payload_json '
                'FROM environments ORDER BY max_distance DESC,last_seen DESC LIMIT ?',
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            payload = json.loads(row['payload_json'])
            payload.update({
                'environment_key': row['environment_key'],
                'first_seen': row['first_seen'],
                'last_seen': row['last_seen'],
                'times_seen': row['times_seen'],
                'max_distance': row['max_distance'],
            })
            out.append(payload)
        return out

    def cognitive_overview(self, profiles: dict[str, SourceProfile]) -> dict:
        context = self.cognitive_context(profiles)
        return {
            'coverage': context['coverage'],
            'underexplored_categories': context['underexplored_categories'],
            'assumptions': context['assumptions'],
            'recent_model_challenges': context['recent_model_challenges'],
            'environments': self.environments(30),
        }
