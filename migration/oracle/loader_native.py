"""SHA-bound BIRD dev loader: ordinary PDB users and original quoted names."""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import oracledb

POLICY_PATH = Path(__file__).resolve().parents[2] / 'data/schemas/oracle_storage.json'
ORACLE_DSN = os.getenv('UNIQL_ORACLE_DSN', 'localhost:1521/FREEPDB1')
DEFAULT_USER_PASS = os.getenv('UNIQL_ORACLE_USER_PASSWORD', '<ORACLE_PASSWORD>')

def quote_identifier(name):
    if not isinstance(name, str) or not name or '\x00' in name or len(name.encode('utf-8')) > 128:
        raise ValueError('Invalid Oracle identifier')
    return '"' + name.replace('"', '""') + '"'

def username_for(db_id):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_$#]{0,127}', db_id, flags=re.ASCII):
        raise ValueError('Invalid benchmark database identifier')
    return db_id.upper()

def setup_oracle_user(admin_conn, username, *, recreate=False):
    username = username_for(username)
    with admin_conn.cursor() as cursor:
        cursor.execute("SELECT SYS_CONTEXT('USERENV','CON_NAME') FROM DUAL")
        if cursor.fetchone()[0] in ('CDB$ROOT', 'PDB$SEED'):
            raise ValueError('Connect to a writable PDB service, such as FREEPDB1')
        cursor.execute('SELECT oracle_maintained FROM dba_users WHERE username=:u', u=username)
        existing = cursor.fetchone()
        if existing:
            if existing[0] == 'Y':
                raise ValueError('Refusing to replace an Oracle-maintained user')
            if not recreate:
                raise ValueError('User already exists; --recreate explicitly replaces its benchmark data')
            cursor.execute('DROP USER ' + quote_identifier(username) + ' CASCADE')
        cursor.execute('CREATE USER ' + quote_identifier(username) + ' IDENTIFIED BY ' + quote_identifier(DEFAULT_USER_PASS) + ' DEFAULT TABLESPACE USERS QUOTA UNLIMITED ON USERS')
        cursor.execute('GRANT CREATE SESSION, CREATE TABLE TO ' + quote_identifier(username))
        cursor.execute('SELECT oracle_maintained FROM dba_users WHERE username=:u', u=username)
        if cursor.fetchone() != ('N',):
            raise RuntimeError('Created user is not an ordinary PDB user')

def storage_value(value, column):
    if value is None:
        return None
    kind = column['logical_type']
    if kind == 'VARCHAR':
        if isinstance(value, bytes):
            raise ValueError('Binary value in text column')
        return str(value)
    if kind == 'BIGINT':
        if type(value) is not int or not -(2**63) <= value < 2**63:
            raise ValueError('Expected signed int64')
        return value
    if kind == 'DOUBLE':
        if type(value) not in (int, float):
            raise ValueError('Expected numeric value')
        return float(value)
    if kind == 'BLOB':
        return value.encode('utf-8') if isinstance(value, str) else bytes(value)
    raise ValueError('Unknown storage policy')

class Fingerprint:
    def __init__(self):
        self.rows, self.total = 0, 0
    def add(self, row, columns):
        encoded = []
        for value, col in zip(row, columns):
            kind = col['logical_type']
            if value is None:
                encoded.append(['null'])
            elif kind == 'BIGINT':
                if Decimal(value) != int(value):
                    raise ValueError('Fractional integer readback')
                encoded.append(['int', str(int(value))])
            elif kind == 'DOUBLE':
                encoded.append(['double', float(value).hex()])
            elif kind == 'BLOB':
                encoded.append(['blob', bytes(value).hex()])
            else:
                encoded.append(['text', value])
        raw = json.dumps(encoded, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.total = (self.total + int.from_bytes(hashlib.sha256(raw).digest(), 'big')) % (2**256)
        self.rows += 1
    def evidence(self):
        return {'rows': self.rows, 'sha256_multiset_sum': format(self.total, '064x')}

def source_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024**2), b''):
            h.update(block)
    return h.hexdigest()

def load_database(connection, source_path, db_id, *, policy_path=POLICY_PATH, progress=None):
    policy = json.loads(Path(policy_path).read_text())['databases'][db_id]
    source_path = Path(source_path).resolve(strict=True)
    digest = source_digest(source_path)
    if digest != policy['source_sha256']:
        raise ValueError('Source database differs from the published storage manifest')
    reports = []
    with sqlite3.connect(source_path.as_uri() + '?mode=ro&immutable=1', uri=True) as source:
        source.execute('PRAGMA query_only=ON')
        with connection.cursor() as cursor:
            for table in policy['tables']:
                columns = table['columns']
                name = quote_identifier(table['target_name'])
                declarations = [quote_identifier(c['target_name']) + ' ' + c['physical_type'] for c in columns]
                primary = sorted([c for c in columns if c['pk']], key=lambda c: c['pk'])
                if primary and all(c['logical_type'] == 'BIGINT' for c in primary):
                    declarations.append('PRIMARY KEY (' + ','.join(quote_identifier(c['target_name']) for c in primary) + ')')
                cursor.execute('CREATE TABLE ' + name + ' (' + ','.join(declarations) + ')')
                expressions, bindings = [], []
                for column in columns:
                    position, physical = len(bindings) + 1, column['physical_type']
                    if physical in ('CLOB', 'BLOB'):
                        expressions.append('CASE WHEN :%d=1 THEN EMPTY_%s() ELSE :%d END' % (position, physical, position + 1))
                        bindings.extend([oracledb.DB_TYPE_NUMBER, oracledb.DB_TYPE_CLOB if physical == 'CLOB' else oracledb.DB_TYPE_BLOB])
                    else:
                        expressions.append(':%d' % position)
                        bindings.append(oracledb.DB_TYPE_BINARY_DOUBLE if physical == 'BINARY_DOUBLE' else oracledb.DB_TYPE_NUMBER if physical.startswith('NUMBER') else 4000)
                insert = 'INSERT INTO ' + name + ' VALUES (' + ','.join(expressions) + ')'
                scan = source.execute('SELECT * FROM ' + quote_identifier(table['name']))
                expected = Fingerprint()
                cursor.setinputsizes(*bindings)
                while True:
                    rows = scan.fetchmany(64)
                    if not rows:
                        break
                    # Bind short CLOB payloads as scalar text. This avoids a
                    # temporary LOB per cell while preserving the stored CLOB.
                    active_bindings, active_expressions = [], []
                    for i, column in enumerate(columns):
                        position = len(active_bindings) + 1
                        physical = column['physical_type']
                        if physical in ('CLOB', 'BLOB'):
                            scalar = physical == 'CLOB' and all(v[i] is None or len(str(v[i]).encode('utf-8')) <= 4000 for v in rows)
                            active_bindings.extend([oracledb.DB_TYPE_NUMBER, 4000 if scalar else oracledb.DB_TYPE_CLOB if physical == 'CLOB' else oracledb.DB_TYPE_BLOB])
                            value = 'TO_CLOB(:%d)' % (position+1) if scalar else ':%d' % (position+1)
                            active_expressions.append('CASE WHEN :%d=1 THEN EMPTY_%s() ELSE %s END' % (position, physical, value))
                        else:
                            active_expressions.append(':%d' % position)
                            active_bindings.append(oracledb.DB_TYPE_BINARY_DOUBLE if physical == 'BINARY_DOUBLE' else oracledb.DB_TYPE_NUMBER if physical.startswith('NUMBER') else 4000)
                    batch = []
                    for row in rows:
                        stored = [storage_value(v, c) for v, c in zip(row, columns)]
                        expected.add(stored, columns)
                        params = []
                        for value, column in zip(stored, columns):
                            if column['physical_type'] in ('CLOB', 'BLOB'):
                                params.extend([int(value is not None and len(value) == 0), value])
                            else:
                                params.append(value)
                        batch.append(params)
                    cursor.setinputsizes(*active_bindings)
                    cursor.executemany('INSERT INTO ' + name + ' VALUES (' + ','.join(active_expressions) + ')', batch)
                    connection.commit()
                actual = Fingerprint()
                cursor.outputtypehandler = lambda cur, meta: cur.var(oracledb.DB_TYPE_VARCHAR, size=172, arraysize=cur.arraysize, outconverter=Decimal) if meta.type_code == oracledb.DB_TYPE_NUMBER else None
                lob_indices = [i for i, c in enumerate(columns) if c['physical_type'] in ('CLOB', 'BLOB')]
                projection = [quote_identifier(c['target_name']) for c in columns]
                for i in lob_indices:
                    q = quote_identifier(columns[i]['target_name'])
                    projection.append('CASE WHEN ' + q + ' IS NULL THEN -1 ELSE DBMS_LOB.GETLENGTH(' + q + ') END')
                cursor.execute('SELECT ' + ','.join(projection) + ' FROM ' + name, fetch_lobs=False)
                for row in cursor:
                    values = list(row[:len(columns)])
                    for j, i in enumerate(lob_indices):
                        if row[len(columns)+j] == 0:
                            values[i] = '' if columns[i]['physical_type'] == 'CLOB' else b''
                    actual.add([v.read() if hasattr(v, 'read') else v for v in values], columns)
                cursor.outputtypehandler = None
                if actual.evidence() != expected.evidence() or actual.rows != table['rows']:
                    raise RuntimeError('Full strict verification failed for ' + table['name'] + ': expected ' + json.dumps(expected.evidence()) + ', actual ' + json.dumps(actual.evidence()))
                report = {'table': table['name'], 'source': expected.evidence(), 'target': actual.evidence(), 'content_verified': True}
                reports.append(report)
                if progress:
                    progress(report)
                for i, column in enumerate(columns):
                    if not column['pk'] and column['logical_type'] == 'BIGINT' and ('id' in column['name'].lower() or 'code' in column['name'].lower()):
                        index = 'uq_ix_' + hashlib.sha256((table['name'] + ':' + str(i)).encode()).hexdigest()[:24]
                        cursor.execute('CREATE INDEX ' + quote_identifier(index) + ' ON ' + name + ' (' + quote_identifier(column['target_name']) + ')')
    return {'db_id': db_id, 'source_sha256': digest, 'content_verified': True, 'tables': reports}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=os.getenv('UNIQL_BIRD_DB_ROOT', '<BIRD_DEV_DATABASES>'))
    parser.add_argument('--databases', nargs='+')
    parser.add_argument('--recreate', action='store_true', help='Explicitly replace existing ordinary benchmark users and their data')
    args = parser.parse_args()
    policy = json.loads(POLICY_PATH.read_text())['databases']
    with oracledb.connect(user=os.getenv('UNIQL_ORACLE_ADMIN_USER', 'SYSTEM'), password=os.getenv('UNIQL_ORACLE_ADMIN_PASSWORD', '<ORACLE_ADMIN_PASSWORD>'), dsn=ORACLE_DSN) as admin:
        for db in args.databases or list(policy):
            if db not in policy:
                raise ValueError('Unknown BIRD dev database')
            user = username_for(db)
            setup_oracle_user(admin, user, recreate=args.recreate)
            with oracledb.connect(user=user, password=DEFAULT_USER_PASS, dsn=ORACLE_DSN) as connection:
                report = load_database(connection, Path(args.root) / db / (db + '.sqlite'), db)
            print(json.dumps({'db_id': db, 'tables': len(report['tables']), 'content_verified': True}))

if __name__ == '__main__':
    main()
