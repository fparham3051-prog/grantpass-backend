#!/usr/bin/env python3
"""Restore an InstitutionalOS backup (the JSON from GET /integration/backup,
saved nightly by the operations app) into a Postgres database.

    DATABASE_URL=postgres://... python3 scripts/restore_backup.py backup.json [--replace]

Without --replace it refuses to touch a database that already has
organizations, so it can't overwrite live data by accident. With --replace
it empties each table in the backup first. Run it against a fresh database,
check it, then point the service at it.
"""
import json, os, sys
import psycopg2, psycopg2.extras

def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path, replace = sys.argv[1], '--replace' in sys.argv
    data = json.load(open(path))
    if 'institutionalos' in data:  # full-system bundle from the operations app
        data = data['institutionalos']
    tables = data['tables']
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    import db
    db.init_db()  # create any missing tables and columns first
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM organizations")
    if cur.fetchone()[0] and not replace:
        sys.exit('organizations already has rows; pass --replace to overwrite')
    cur.execute("SET session_replication_role = replica")  # skip FK order issues
    for t, rows in tables.items():
        if replace:
            cur.execute(f'DELETE FROM "{t}"')
        if not rows:
            continue
        cols = list(rows[0].keys())
        cur.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name=%s", (t,))
        types = dict(cur.fetchall())
        def val(c, v):
            if v is not None and types.get(c) in ('json', 'jsonb') and not isinstance(v, str):
                return json.dumps(v)
            return v
        psycopg2.extras.execute_values(
            cur, f'INSERT INTO "{t}" ({",".join(chr(34)+c+chr(34) for c in cols)}) VALUES %s',
            [tuple(val(c, r.get(c)) for c in cols) for r in rows])
        # keep id sequences ahead of restored ids
        if 'id' in cols and types.get('id') in ('integer', 'bigint'):
            cur.execute(f"SELECT pg_get_serial_sequence('\"{t}\"','id')")
            seq = cur.fetchone()[0]
            if seq:
                cur.execute(f'SELECT setval(%s, (SELECT COALESCE(MAX(id),1) FROM "{t}"))', (seq,))
        print(f'{t}: {len(rows)} rows')
    cur.execute("SET session_replication_role = DEFAULT")
    conn.commit()
    print('restore complete')

if __name__ == '__main__':
    main()
