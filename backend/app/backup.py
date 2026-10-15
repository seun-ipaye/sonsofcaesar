"""Database backups: every table exported to one zip, kept in a PRIVATE R2 bucket.

Why not pg_dump: it must match the database server's exact version, which is fragile
on a hosted database. This exports each table with Postgres' own COPY instead, so
it works with any version, and restores into an empty database at the same migration.

A backup zip contains:
  manifest.json      when it was made, the migration version, row counts
  <table>.csv        one file per table, with a header row
"""

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.config import settings
from app.db import Base
from app import models  # noqa: F401  (registers the tables)

KEEP = 60  # backups to keep (every 6 hours = about 15 days)
ALEMBIC_INI = Path(__file__).resolve().parent.parent / 'alembic.ini'
PREFIX = 'db/'


def _tables() -> list[str]:
    # Parents before children, so restoring never breaks a foreign key
    return [t.name for t in Base.metadata.sorted_tables]


def _raw(engine):
    return engine.raw_connection().driver_connection  # psycopg connection, for COPY


def dump(database_url: str | None = None) -> tuple[bytes, dict]:
    """Export the whole database. Returns (zip bytes, manifest)."""
    engine = create_engine(database_url or settings.sqlalchemy_url)
    conn = _raw(engine)
    buf = io.BytesIO()
    manifest = {'created_at': datetime.now(UTC).isoformat(), 'tables': {}}
    try:
        # One consistent snapshot of all tables, even if sales happen mid-backup
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            manifest['migration'] = conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                for table in _tables():
                    data = io.BytesIO()
                    with conn.cursor().copy(f'COPY (SELECT * FROM "{table}") TO STDOUT WITH CSV HEADER') as copy:
                        for chunk in copy:
                            data.write(chunk)
                    z.writestr(f'{table}.csv', data.getvalue())
                    manifest['tables'][table] = max(data.getvalue().count(b'\n') - 1, 0)
                z.writestr('manifest.json', json.dumps(manifest, indent=2))
    finally:
        conn.close()
        engine.dispose()
    return buf.getvalue(), manifest


def restore(zip_bytes: bytes, database_url: str) -> dict:
    """Load a backup into an EMPTY database. Creates the tables at the backup's
    migration version, then copies every row back in."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        manifest = json.loads(z.read('manifest.json'))
        url = database_url
        for prefix in ('postgres://', 'postgresql://'):
            if url.startswith(prefix):
                url = 'postgresql+psycopg://' + url[len(prefix):]

        engine = create_engine(url)
        with engine.connect() as c:
            existing = c.execute(
                text("select count(*) from information_schema.tables where table_schema = 'public'")
            ).scalar()
        if existing:
            engine.dispose()
            raise RuntimeError('That database is not empty. Restore only into a fresh, empty database.')

        # Recreate the tables exactly as they were at backup time
        cfg = Config(str(ALEMBIC_INI))
        cfg.attributes['database_url'] = url  # migrate the target, not the app's own database
        command.upgrade(cfg, manifest['migration'])

        conn = _raw(engine)
        try:
            with conn.transaction():
                for table in _tables():
                    name = f'{table}.csv'
                    if name not in z.namelist():
                        continue
                    with conn.cursor().copy(f'COPY "{table}" FROM STDIN WITH CSV HEADER') as copy:
                        copy.write(z.read(name))
                    # Keep auto-numbered ids counting on from the highest restored one
                    seq = conn.execute(f"SELECT pg_get_serial_sequence('\"{table}\"', 'id')").fetchone()[0]
                    if seq:
                        top = conn.execute(f'SELECT MAX(id) FROM "{table}"').fetchone()[0]
                        conn.execute('SELECT setval(%s, %s, %s)', (seq, top or 1, top is not None))
        finally:
            conn.close()
            engine.dispose()
    return manifest


# ---------- R2 (private bucket) ----------


def _bucket():
    import boto3

    if not (settings.backup_r2_account_id and settings.backup_r2_access_key_id and settings.backup_r2_secret_access_key):
        raise RuntimeError('Backup bucket not configured (BACKUP_R2_* variables)')
    s3 = boto3.client(
        's3',
        endpoint_url=f'https://{settings.backup_r2_account_id}.r2.cloudflarestorage.com',
        aws_access_key_id=settings.backup_r2_access_key_id,
        aws_secret_access_key=settings.backup_r2_secret_access_key,
        region_name='auto',
    )
    return s3, settings.backup_r2_bucket


def upload(zip_bytes: bytes, manifest: dict) -> str:
    s3, bucket = _bucket()
    key = f'{PREFIX}{manifest["created_at"][:16].replace(":", "")}Z.zip'  # e.g. db/2026-10-15T0900Z.zip
    s3.put_object(Bucket=bucket, Key=key, Body=zip_bytes, ContentType='application/zip')
    return key


def list_backups() -> list[dict]:
    s3, bucket = _bucket()
    items = s3.list_objects_v2(Bucket=bucket, Prefix=PREFIX).get('Contents', [])
    return sorted(
        ({'key': o['Key'], 'size': o['Size'], 'modified': o['LastModified']} for o in items),
        key=lambda o: o['key'],
        reverse=True,
    )


def prune(keep: int = KEEP) -> int:
    s3, bucket = _bucket()
    old = list_backups()[keep:]
    for o in old:
        s3.delete_object(Bucket=bucket, Key=o['key'])
    return len(old)


def download(key: str) -> bytes:
    s3, bucket = _bucket()
    return s3.get_object(Bucket=bucket, Key=key)['Body'].read()
