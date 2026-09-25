/** Synthetic data only. Caller must provide a disposable HOME and deny network. */
import assert from 'node:assert/strict';
import { mkdirSync, writeFileSync, symlinkSync, chmodSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

const [packageRoot, helper] = Bun.argv.slice(2);
const home = homedir();
let engine;
try {
  const metadata = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8'));
  assert.equal(metadata.name, 'gbrain');
  assert.equal(metadata.version, '0.48.2.0');
  const { PGLiteEngine } = await import(pathToFileURL(join(packageRoot, 'src/core/pglite-engine.ts')).href);
  const database = join(home, '.gbrain', 'fixture.pglite');
  mkdirSync(join(home, '.gbrain'), { recursive: true, mode: 0o700 });
  mkdirSync(join(home, '.bun/bin'), { recursive: true, mode: 0o700 });
  mkdirSync(join(home, '.bun/install/global/node_modules'), { recursive: true, mode: 0o700 });
  symlinkSync(join(packageRoot, 'src/cli.ts'), join(home, '.bun/bin/gbrain'));
  symlinkSync(packageRoot, join(home, '.bun/install/global/node_modules/gbrain'));
  engine = new PGLiteEngine();
  await engine.connect({database_path: database});
  await engine.initSchema();
  await engine.executeRaw("INSERT INTO sources(id,name) VALUES ('x-bookmarks','x-bookmarks'),('unrelated-fixture','unrelated-fixture')");
  await engine.executeRaw("UPDATE sources SET last_commit=$1,last_sync_at=$2 WHERE id='x-bookmarks'", ['a'.repeat(40), '2026-09-25T14:00:00Z']);
  for (const [id, source, frontmatter] of [
    ['verified', 'x-bookmarks', {status: 'published'}],
    ['quarantined', 'x-bookmarks', {status: 'unverified', provenance: 'auto-extracted'}],
    ['excluded', 'unrelated-fixture', {status: 'published'}],
  ] as const) {
    await engine.putPage(`bookmarks/${id}`, {type:'note',title:`Geometry ${id}`,compiled_truth:'Geometry spacing fixture',timeline:'',frontmatter}, {sourceId:source});
    await engine.upsertChunks(`bookmarks/${id}`, [{chunk_index:0,chunk_text:'Geometry spacing fixture',chunk_source:'compiled_truth',token_count:3}], {sourceId:source});
  }
  await engine.disconnect(); engine = undefined;
  chmodSync(database, 0o700);
  const config = JSON.stringify({engine:'pglite',database_path:database});
  writeFileSync(join(home,'.gbrain/config.json'), config, {mode:0o600});
  function invoke(operation) {
    const child = Bun.spawnSync(['/opt/homebrew/bin/bun','--no-env-file',helper], {
      env:{HOME:home,PATH:'/opt/homebrew/bin:/usr/bin:/bin',GBRAIN_SOURCE:'x-bookmarks',GBRAIN_CLI_PATH:join(packageRoot,'src/cli.ts'),GBRAIN_CONFIG_SHA256:createHash('sha256').update(config).digest('hex')},
      stdin:Buffer.from(JSON.stringify({schema_version:1,source:'x-bookmarks',...operation})),
      stdout:'pipe',stderr:'pipe',timeout:30000,
    });
    assert.equal(child.exitCode,0,'helper failed closed');
    return JSON.parse(child.stdout.toString());
  }
  const status = invoke({operation:'sources_status'});
  assert.equal(status.id,'x-bookmarks');
  assert.equal(status.page_count,2);
  assert.equal(status.last_commit,'a'.repeat(40));
  assert.equal(status.archived,false);
  assert.equal(status.clone_state,'not-applicable');
  assert.equal(new Date(status.last_sync_at).toISOString(),'2026-09-25T14:00:00.000Z');
  const rows = invoke({operation:'keyword',query:'geometry',limit:10});
  assert.equal(rows.length,2);
  assert(rows.every((row)=>row.source_id==='x-bookmarks'));
  assert.equal(rows.find((row)=>row.slug==='bookmarks/quarantined')?.unverified,true);
  assert.notEqual(rows.find((row)=>row.slug==='bookmarks/verified')?.unverified,true);
  console.log(JSON.stringify({ok:true,rows}));
} catch {
  console.log(JSON.stringify({ok:false,reason:'isolated_runtime_contract_failed'}));
  process.exitCode=1;
} finally { await engine?.disconnect(); }
