"""Consistent, read-only source snapshot for the CURRENT Radar schema.

Never initializes the application, decrypts credentials, changes the live database,
or executes remote SQL. Output contains private data and MUST stay out of Git.
"""
import argparse
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def identifier(value):
    return '"'+str(value).replace('"','""')+'"'


def literal(value):
    if value is None: return 'NULL'
    if isinstance(value, bytes): return "X'"+value.hex()+"'"
    if isinstance(value, (int,float)):
        if isinstance(value,float) and not math.isfinite(value): raise ValueError('Non-finite SQLite value')
        return str(value)
    text=str(value)
    if '\x00' in text: return "CAST(X'"+text.encode('utf-8').hex()+"' AS TEXT)"
    return "'"+text.replace("'","''")+"'"


def table_order(db, tables):
    ordered=[]; remaining=set(tables)
    while remaining:
        ready=sorted(t for t in remaining if not {
            row[2] for row in db.execute('PRAGMA foreign_key_list('+identifier(t)+')')
            if row[2]!=t
        } & remaining)
        if not ready: raise ValueError('Cyclic schema requires explicit migration strategy')
        ordered.extend(ready); remaining.difference_update(ready)
    return ordered


def export_current(source, destination, chunk_rows=400):
    source=Path(source).resolve(strict=True); destination=Path(destination).resolve()
    if chunk_rows<1 or chunk_rows>1000: raise ValueError('chunk_rows must be 1..1000')
    if destination.exists(): raise FileExistsError('Output already exists; refusing overwrite')
    destination.mkdir(parents=True)
    snapshot=destination/'snapshot.sqlite'
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as live, closing(sqlite3.connect(snapshot)) as copy:
        live.backup(copy)
    files=[]; counts={}; digests={}
    with closing(sqlite3.connect(snapshot)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Source integrity check failed; no remote import allowed')
        schema=[row[0]+';' for row in db.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,name")]
        (destination/'schema.sql').write_text('\n\n'.join(schema)+'\n',encoding='utf-8')
        tables=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in table_order(db,tables):
            columns=[r[1] for r in db.execute('PRAGMA table_info('+identifier(table)+')')]
            primary=sorted((r[5],r[1]) for r in db.execute('PRAGMA table_info('+identifier(table)+')') if r[5])
            order=','.join(identifier(name) for _,name in primary) or 'rowid'
            cursor=db.execute('SELECT * FROM '+identifier(table)+' ORDER BY '+order)
            total=0; sequence=0; digest=hashlib.sha256()
            while True:
                rows=cursor.fetchmany(chunk_rows)
                if not rows: break
                statements=[]; tuples=[]; statement_bytes=0
                prefix='INSERT INTO '+identifier(table)+'('+','.join(map(identifier,columns))+') VALUES'
                for row in rows:
                    values='('+','.join(map(literal,row))+')'
                    sql=prefix+values+';'
                    digest.update((sql+'\n').encode('utf-8'))
                    size=len(values.encode('utf-8'))+1
                    if tuples and (len(tuples)>=100 or statement_bytes+size+len(prefix.encode('utf-8'))>80000):
                        statements.append(prefix+','.join(tuples)+';'); tuples=[]; statement_bytes=0
                    if size+len(prefix.encode('utf-8'))>80000: raise ValueError('Single record exceeds safe D1 SQL size; use bounded parameter import')
                    tuples.append(values); statement_bytes+=size
                if tuples: statements.append(prefix+','.join(tuples)+';')
                filename=f'data-{len(files)+1:05d}-{table}-{sequence:04d}.sql'
                (destination/filename).write_text('\n'.join(statements)+'\n',encoding='utf-8')
                files.append(filename); total+=len(rows); sequence+=1
            counts[table]=total; digests[table]=digest.hexdigest()
        # Preserve high-water sequence IDs even if the highest event was deleted.
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone():
            seq=[]
            for name,value in db.execute('SELECT name,seq FROM sqlite_sequence ORDER BY name'):
                if name in tables:
                    seq.extend(['DELETE FROM sqlite_sequence WHERE name='+literal(name)+';',
                                'INSERT INTO sqlite_sequence(name,seq) VALUES('+literal(name)+','+literal(value)+');'])
            if seq:
                filename='data-sequences.sql'; files.append(filename)
                (destination/filename).write_text('\n'.join(seq)+'\n',encoding='utf-8')
    file_hashes={name:hashlib.sha256((destination/name).read_bytes()).hexdigest() for name in ['schema.sql',*files]}
    manifest={'format':1,'created_at':datetime.now(timezone.utc).isoformat(),'source':str(source),
              'snapshot_sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest(),
              'counts':counts,'table_sha256':digests,'data_files':files,'file_sha256':file_hashes,
              'contains_private_data':True,'remote_import_performed':False}
    (destination/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--chunk-rows',type=int,default=400)
    args=parser.parse_args(); report=export_current(args.source,args.output,args.chunk_rows)
    print(json.dumps({'tables':len(report['counts']),'counts':report['counts'],'files':len(report['data_files']),
                      'snapshot_sha256':report['snapshot_sha256'],'remote_import_performed':False},indent=2))
