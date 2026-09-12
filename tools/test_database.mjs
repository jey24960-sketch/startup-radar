// Local PostgreSQL engine for integration tests only. Not a Supabase Auth emulator.
import {PGlite} from '@electric-sql/pglite';
import {PGLiteSocketServer} from '@electric-sql/pglite-socket';
import {readFile,readdir} from 'node:fs/promises';
const db=await PGlite.create();
await db.exec(`create schema auth; create role anon; create role authenticated; create role service_role bypassrls;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
await db.exec(await readFile('tests/fixtures/gfc_identity.sql','utf8'));
for(const file of (await readdir('supabase/migrations')).filter(f=>f.endsWith('.sql')).sort()) await db.exec(await readFile('supabase/migrations/'+file,'utf8'));
await db.exec("create table public.radar_test_marker(value text primary key); insert into public.radar_test_marker values('ephemeral-test-only');");
const server=new PGLiteSocketServer({db,host:'127.0.0.1',port:Number(process.env.RADAR_TEST_PORT || 55432),maxConnections:10});
await server.start();
console.log('TEST_DATABASE_READY port='+ (process.env.RADAR_TEST_PORT || 55432));
process.on('SIGINT',async()=>{await server.stop();await db.close();process.exit(0)});
