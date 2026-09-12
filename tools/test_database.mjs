// Local PostgreSQL engine for integration tests only. Not a Supabase Auth emulator.
import {PGlite} from '@electric-sql/pglite';
import {PGLiteSocketServer} from '@electric-sql/pglite-socket';
import {readFile,readdir} from 'node:fs/promises';
const db=await PGlite.create();
await db.exec(`create schema auth; create role anon; create role authenticated; create role service_role bypassrls;
create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
for(const file of (await readdir('supabase/migrations')).filter(f=>f.endsWith('.sql')).sort()) await db.exec(await readFile('supabase/migrations/'+file,'utf8'));
const server=new PGLiteSocketServer({db,host:'127.0.0.1',port:55432});
await server.start();
console.log('TEST_DATABASE_READY port=55432 (ephemeral test database; no production data)');
process.on('SIGINT',async()=>{await server.stop();await db.close();process.exit(0)});
