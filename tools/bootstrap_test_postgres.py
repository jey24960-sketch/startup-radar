"""Bootstrap an EMPTY loopback radar_test database. Never use with hosted data."""
import os
from pathlib import Path
import psycopg


def main():
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        if c.info.host not in ('127.0.0.1','localhost','::1') or c.info.dbname!='radar_test':
            raise ValueError('Only the loopback radar_test database may be initialized')
        if c.execute("select 1 from pg_namespace where nspname in ('radar','startup_radar','auth')").fetchone():
            raise ValueError('Test database already initialized; bootstrap refuses to overwrite it')
        for role in ('anon','authenticated','service_role'):
            if not c.execute('select 1 from pg_roles where rolname=%s',(role,)).fetchone():
                c.execute(psycopg.sql.SQL('create role {} {}').format(psycopg.sql.Identifier(role),psycopg.sql.SQL('bypassrls' if role=='service_role' else '')))
        c.execute('create schema auth; create table auth.users(id uuid primary key)')
        c.execute("create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$")
        c.execute('grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated')
        c.execute(Path('tests/fixtures/gfc_identity.sql').read_text(encoding='utf-8'))
        for migration in sorted(Path('supabase/migrations').glob('*.sql')):c.execute(migration.read_text(encoding='utf-8'))
        c.execute("create table public.radar_test_marker(value text primary key); insert into public.radar_test_marker values('ephemeral-test-only')")
    print('Native PostgreSQL test schema initialized (mock Auth identities only)')


if __name__=='__main__':main()
