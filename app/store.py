from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .models import FeedbackRequest, RawItem, RunResult, SavedGoal


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

    def _init(self) -> None:
        with self._connect() as db:
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
            ''')

    def history(self, item_ids: list[str]) -> dict[str, dict]:
        if not item_ids:
            return {}
        placeholders = ','.join('?' for _ in item_ids)
        with self._connect() as db:
            rows = db.execute(
                f'SELECT item_id, first_seen, last_seen, seen_count FROM items WHERE item_id IN ({placeholders})',
                item_ids,
            ).fetchall()
        return {row['item_id']: dict(row) for row in rows}

    def source_weights(self) -> dict[str, float]:
        with self._connect() as db:
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
        with self._lock, self._connect() as db:
            db.execute('INSERT OR IGNORE INTO source_health(source) VALUES(?)', (source,))
            if ok:
                db.execute('UPDATE source_health SET successes=successes+1,last_ok=? WHERE source=?', (now, source))
            else:
                db.execute('''UPDATE source_health SET failures=failures+1,last_error=?,last_error_at=? WHERE source=?''', (error[:1000], now, source))

    def observe_items(self, items: list[RawItem]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock, self._connect() as db:
            for item in items:
                db.execute('''
                    INSERT INTO items(item_id,source,title,url,first_seen,last_seen,seen_count,last_score,last_disposition)
                    VALUES(?,?,?,?,?,?,1,0,'background')
                    ON CONFLICT(item_id) DO UPDATE SET
                        last_seen=excluded.last_seen, seen_count=items.seen_count+1,
                        title=excluded.title, url=excluded.url
                ''', (item.id, item.source, item.title, item.url, now, now))

    def record_run(self, result: RunResult) -> None:
        now = result.created_at.isoformat()
        payload = result.model_dump_json()
        with self._lock, self._connect() as db:
            db.execute(
                'INSERT OR REPLACE INTO runs(run_id,created_at,goal,raw_count,filtered_count,payload_json) VALUES(?,?,?,?,?,?)',
                (result.run_id, now, result.plan.goal, result.raw_count, result.filtered_count, payload),
            )
            for item in result.items:
                db.execute('UPDATE items SET last_score=?,last_disposition=? WHERE item_id=?',
                           (item.score, item.disposition, item.id))

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._connect() as db:
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
            })
        return out

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute('SELECT payload_json FROM runs WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row['payload_json']) if row else None

    def add_feedback(self, feedback: FeedbackRequest) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                'INSERT INTO feedback(item_id,source,useful,note,created_at) VALUES(?,?,?,?,?)',
                (feedback.item_id, feedback.source, int(feedback.useful), feedback.note, datetime.now(timezone.utc).isoformat()),
            )

    def list_goals(self) -> list[SavedGoal]:
        with self._connect() as db:
            rows = db.execute('SELECT name,prompt,horizon_hours,enabled FROM goals ORDER BY name').fetchall()
        return [SavedGoal(name=r['name'], prompt=r['prompt'], horizon_hours=r['horizon_hours'], enabled=bool(r['enabled'])) for r in rows]

    def save_goal(self, goal: SavedGoal) -> None:
        with self._lock, self._connect() as db:
            db.execute('''
                INSERT INTO goals(name,prompt,horizon_hours,enabled,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET prompt=excluded.prompt,horizon_hours=excluded.horizon_hours,
                    enabled=excluded.enabled,updated_at=excluded.updated_at
            ''', (goal.name, goal.prompt, goal.horizon_hours, int(goal.enabled), datetime.now(timezone.utc).isoformat()))

    def delete_goal(self, name: str) -> None:
        with self._lock, self._connect() as db:
            db.execute('DELETE FROM goals WHERE name=?', (name,))

    def health(self) -> list[dict]:
        with self._connect() as db:
            rows = db.execute('SELECT * FROM source_health ORDER BY source').fetchall()
        return [dict(r) for r in rows]
