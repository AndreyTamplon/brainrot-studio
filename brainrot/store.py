import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from tempfile import NamedTemporaryFile

from .config import DATA, TOTAL_BUDGET
from .review_policy import accepted


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def write_json(path, value):
    with NamedTemporaryFile(
        mode="w", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
    ) as handle:
        from pathlib import Path

        temporary = Path(handle.name)
        try:
            handle.write(dumps(value))
            handle.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


@contextmanager
def connection():
    db = sqlite3.connect(DATA / "studio.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        yield db
        db.commit()
    finally:
        db.close()


@contextmanager
def worker_lease():
    """One queue owner per data directory; a crashed process releases its OS lock."""
    import fcntl

    with (DATA / "worker.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Сервер с этой папкой данных уже запущен") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def init(*, recover=True):
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
          status TEXT NOT NULL, stage TEXT NOT NULL, request TEXT NOT NULL,
          artifacts TEXT NOT NULL DEFAULT '{}', error TEXT, parent_id TEXT
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
          time REAL NOT NULL, agent TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS charges (
          id TEXT PRIMARY KEY, job_id TEXT NOT NULL, time REAL NOT NULL,
          model TEXT NOT NULL, purpose TEXT NOT NULL, amount REAL NOT NULL,
          status TEXT NOT NULL, request_id TEXT, tokens INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS charge_rechecks (
          charge_id TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0,
          next_attempt REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS submissions (
          key TEXT PRIMARY KEY, job_id TEXT NOT NULL, payload TEXT NOT NULL
        );
        """)
        if not recover:
            return
        db.execute(
            "UPDATE jobs SET status='queued', stage='recovering', error=NULL WHERE status='running'"
        )
        stale = [
            ("Обновлены проверки качества. Продолжите задание для повторной проверки.", row["id"])
            for row in db.execute("SELECT id,artifacts FROM jobs WHERE status='ready'")
            if not accepted(json.loads(row["artifacts"]))
        ]
        db.executemany("UPDATE jobs SET status='needs_review', error=? WHERE id=?", stale)


def create_job(request: dict, parent_id: str | None = None, artifacts=None, submission_key=None):
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        payload = {"request": request, "parent_id": parent_id}
        if submission_key:
            previous = db.execute(
                "SELECT * FROM submissions WHERE key=?", (submission_key,)
            ).fetchone()
            if previous:
                if json.loads(previous["payload"]) != payload:
                    raise ValueError("Ключ повтора уже использован для другого запроса")
                return previous["job_id"]
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                job_id,
                now,
                now,
                "queued",
                "queued",
                dumps(request),
                dumps(artifacts or {}),
                None,
                parent_id,
            ),
        )
        if submission_key:
            db.execute(
                "INSERT INTO submissions VALUES(?,?,?)", (submission_key, job_id, dumps(payload))
            )
    return job_id


def decode(row):
    item = dict(row)
    item["request"] = json.loads(item["request"])
    item["artifacts"] = json.loads(item["artifacts"])
    return item


def get_job(job_id):
    with connection() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return decode(row) if row else None


def list_jobs():
    with connection() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 100").fetchall()
    return [decode(row) for row in rows]


def queued_jobs():
    with connection() as db:
        rows = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created").fetchall()
    return [decode(row) for row in rows]


def update(job_id, **fields):
    allowed = {"status", "stage", "artifacts", "error"}
    if not fields.keys() <= allowed:
        raise ValueError("Unexpected job field")
    fields["updated"] = time.time()
    if "artifacts" in fields:
        fields["artifacts"] = dumps(fields["artifacts"])
    with connection() as db:
        assignments = ",".join(f"{name}=?" for name in fields)
        db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*fields.values(), job_id))


def event(job_id, agent, kind, detail):
    with connection() as db:
        db.execute(
            "INSERT INTO events(job_id,time,agent,kind,detail) VALUES(?,?,?,?,?)",
            (job_id, time.time(), agent, kind, dumps(detail)),
        )


def events(job_id, after=0):
    with connection() as db:
        rows = db.execute(
            "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id", (job_id, after)
        ).fetchall()
    return [{**dict(row), "detail": json.loads(row["detail"])} for row in rows]


class BudgetExceeded(RuntimeError):
    pass


def reserve(job_id: str, model: str, purpose: str, amount: float, job_limit: float):
    charge_id = uuid.uuid4().hex
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        total = db.execute("SELECT COALESCE(SUM(amount),0) FROM charges").fetchone()[0]
        job_total = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM charges WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        if total + amount > TOTAL_BUDGET or job_total + amount > job_limit:
            raise BudgetExceeded("Лимит расходов достигнут. Платные вызовы остановлены.")
        db.execute(
            "INSERT INTO charges VALUES(?,?,?,?,?,?,?,?,?)",
            (
                charge_id,
                job_id,
                time.time(),
                model,
                purpose,
                amount,
                "reserved",
                None,
                0,
            ),
        )
    return charge_id


def settle(charge_id, amount=None, request_id=None, tokens=0, uncertain=False):
    with connection() as db:
        if amount is None:
            db.execute(
                "UPDATE charges SET status=?,request_id=COALESCE(?,request_id) WHERE id=? AND status!='settled'",
                ("uncertain" if uncertain else "estimated", request_id, charge_id),
            )
        else:
            db.execute(
                "UPDATE charges SET amount=?,status='settled',request_id=?,tokens=? WHERE id=?",
                (max(0, amount), request_id, tokens, charge_id),
            )


def usage(job_id=None, *, include_entries=True):
    with connection() as db:
        where = " WHERE job_id=?" if job_id else ""
        params = (job_id,) if job_id else ()
        totals = dict(
            db.execute(
                "SELECT COALESCE(SUM(CASE WHEN status='settled' THEN amount ELSE 0 END),0) AS spent, "
                "COALESCE(SUM(CASE WHEN status!='settled' THEN amount ELSE 0 END),0) AS held, "
                "COALESCE(SUM(tokens),0) AS tokens,COUNT(*) AS calls FROM charges" + where,
                params,
            ).fetchone()
        )
        if include_entries:
            totals["entries"] = [
                dict(row) for row in db.execute("SELECT * FROM charges" + where, params)
            ]
    return {**totals, "limit": TOTAL_BUDGET}


def claim_charge_rechecks(job_id=None, limit=16):
    """Lease due lookups, with persistent backoff, without releasing uncertain money."""
    now = time.time()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT c.*, COALESCE(r.attempts,0) AS attempts FROM charges c "
            "LEFT JOIN charge_rechecks r ON r.charge_id=c.id "
            "WHERE c.status!='settled' AND c.request_id IS NOT NULL AND c.time<? "
            "AND COALESCE(r.next_attempt,0)<=? "
            + ("AND c.job_id=? " if job_id else "")
            + "ORDER BY COALESCE(r.next_attempt,0),c.time LIMIT ?",
            (now - 15, now, *((job_id,) if job_id else ()), limit),
        ).fetchall()
        for row in rows:
            attempts = row["attempts"] + 1
            delay = min(3600, 30 * 2 ** min(attempts - 1, 7))
            db.execute(
                "INSERT INTO charge_rechecks VALUES(?,?,?) ON CONFLICT(charge_id) "
                "DO UPDATE SET attempts=excluded.attempts,next_attempt=excluded.next_attempt",
                (row["id"], attempts, now + delay),
            )
    return [dict(row) for row in rows]
