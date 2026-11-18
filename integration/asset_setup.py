"""Materialize the byte-exact database shipped as a compressed Git LFS asset."""
from pathlib import Path
import gzip
import hashlib
import json
import os
import time
import uuid


def is_sqlite(path):
    if not path.is_file():
        return False
    with path.open('rb') as stream:
        return stream.read(16) == b'SQLite format 3\x00'


def ensure_macro_database(root):
    directory=Path(root)/'vendor/gba/data/processed'
    database=directory/'agent_database.sqlite'
    if is_sqlite(database):
        return database
    if database.exists():
        raise RuntimeError('Macro database is not SQLite. Run git lfs pull; preserve and inspect the invalid local file before retrying.')
    archive=directory/'agent_database.sqlite.gz'
    manifest_path=directory/'agent_database.asset.json'
    if not archive.is_file() or not manifest_path.is_file():
        raise RuntimeError('Macro database asset is missing. Run git lfs install and git lfs pull.')
    with archive.open('rb') as source:
        if source.read(2)!=b'\x1f\x8b':
            raise RuntimeError('Database archive is a Git LFS pointer or invalid file. Run git lfs pull.')
    lock=directory/'agent_database.setup.lock'
    for attempt in range(600):
        try:
            with lock.open('x',encoding='utf-8') as stream:
                stream.write(str(os.getpid()))
            break
        except FileExistsError:
            if is_sqlite(database):
                return database
            time.sleep(0.1)
    else:
        raise RuntimeError('Another database setup is still in progress. Retry after it finishes.')
    temporary=directory/('agent_database.'+uuid.uuid4().hex+'.tmp.sqlite')
    try:
        if is_sqlite(database):
            return database
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
        digest=hashlib.sha256();size=0
        with gzip.open(archive,'rb') as source,temporary.open('xb') as target:
            for chunk in iter(lambda:source.read(4*1024*1024),b''):
                digest.update(chunk);size+=len(chunk);target.write(chunk)
        if size!=manifest['uncompressed_bytes'] or digest.hexdigest()!=manifest['uncompressed_sha256']:
            raise RuntimeError('Database asset checksum mismatch; original local files were not overwritten.')
        if not is_sqlite(temporary):
            raise RuntimeError('Decompressed database is not SQLite.')
        os.replace(temporary,database)
        return database
    finally:
        temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)
