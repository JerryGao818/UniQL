import prestodb
import sys

print("Testing Presto Connection...")
try:
    conn = prestodb.dbapi.connect(
        host='localhost',
        port=8080,
        user='presto',
        catalog='hive',
        schema='default',
    )
    cur = conn.cursor()
    cur.execute('SELECT 1')
    rows = cur.fetchall()
    print(f"Success! Presto Version: {rows[0][0]}")
    cur.close()
    conn.close()
except Exception as e:
    print(f"Presto Connection Failed: {e}")

# Optional: Test Hive if pyhive is available
try:
    from pyhive import hive
    print("\nTesting Hive Connection (via PyHive)...")
    conn = hive.Connection(host='localhost', port=10000, username='hive')
    cur = conn.cursor()
    cur.execute('SELECT 1')
    print(f"Success! Hive Result: {cur.fetchall()}")
    conn.close()
except ImportError:
    print("\nPyHive not installed, skipping Hive connection test.")
except Exception as e:
    print(f"Hive Connection Failed: {e}")
