"""Local durable records and append-only, hash-linked working papers."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(',', ':'))


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.lock = RLock()
        self.path = self.root / 'workbench.sqlite3'
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS papers(job TEXT, seq INTEGER, created TEXT, stage TEXT,
                actor TEXT, body TEXT, previous TEXT, hash TEXT, PRIMARY KEY(job,seq));
            CREATE TRIGGER IF NOT EXISTS immutable_papers_update BEFORE UPDATE ON papers
                BEGIN SELECT RAISE(ABORT, 'working papers are append-only'); END;
            CREATE TRIGGER IF NOT EXISTS immutable_papers_delete BEFORE DELETE ON papers
                BEGIN SELECT RAISE(ABORT, 'working papers are append-only'); END;
            ''')
        self.path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def save(self, kind, ident, body):
        with self.lock, self.connect() as db:
            db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?)', (kind, ident, encode(body)))
        return body

    def get(self, kind, ident):
        with self.connect() as db:
            row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, ident)).fetchone()
        if row is None:
            raise KeyError(ident)
        return json.loads(row[0])

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT body FROM records WHERE kind=? ORDER BY rowid DESC', (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def append(self, job, stage, body, actor='system'):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            last = db.execute('SELECT seq,hash FROM papers WHERE job=? ORDER BY seq DESC LIMIT 1', (job,)).fetchone()
            seq, previous = (last[0] + 1, last[1]) if last else (1, '0' * 64)
            item = {'job': job, 'seq': seq, 'created_at': now(), 'stage': stage, 'actor': actor,
                    'body': body, 'previous_hash': previous}
            digest = hashlib.sha256(encode(item).encode()).hexdigest()
            db.execute('INSERT INTO papers VALUES(?,?,?,?,?,?,?,?)', (job, seq, item['created_at'], stage, actor, encode(body), previous, digest))
        return {**item, 'hash': digest}

    def papers(self, job):
        with self.connect() as db:
            rows = db.execute('SELECT seq,created,stage,actor,body,previous,hash FROM papers WHERE job=? ORDER BY seq', (job,)).fetchall()
        return [{'job': job, 'seq': r[0], 'created_at': r[1], 'stage': r[2], 'actor': r[3],
                 'body': json.loads(r[4]), 'previous_hash': r[5], 'hash': r[6]} for r in rows]

    def verify(self, job):
        previous = '0' * 64
        papers = self.papers(job)
        for seq, paper in enumerate(papers, 1):
            expected = hashlib.sha256(encode({k: v for k, v in paper.items() if k != 'hash'}).encode()).hexdigest()
            if paper['seq'] != seq or paper['previous_hash'] != previous or paper['hash'] != expected:
                return {'valid': False, 'failed_seq': seq, 'count': len(papers)}
            previous = expected
        return {'valid': True, 'count': len(papers), 'head_hash': previous,
                'boundary': '本地哈希链用于完整性检查；未使用外部签名或可信时间戳。'}
