/** Local-only, bounded D1 migration rehearsal. No remote bindings or live SQLite writes. */
import {readFile,mkdir} from 'node:fs/promises';
import {resolve,relative,isAbsolute,join} from 'node:path';
import {createHash} from 'node:crypto';
import {getPlatformProxy,unstable_splitSqlQuery} from 'wrangler';

const [folderArg,persistArg]=process.argv.slice(2);
if(!folderArg||!persistArg)throw Error('Usage: node scripts/local_current.mjs PRIVATE_SNAPSHOT PRIVATE_LOCAL_STATE');
const root=resolve('..'),dataRoot=join(root,'data');
function privatePath(value){const path=resolve(value),child=relative(dataRoot,path);if(!child||child.startsWith('..')||isAbsolute(child))throw Error('All data must remain in an explicit child of ignored data/');return path;}
const folder=privatePath(folderArg),persist=privatePath(persistArg);
const manifest=JSON.parse(await readFile(join(folder,'manifest.json'),'utf8'));
for(const [name,expected]of Object.entries(manifest.file_sha256)){
  const bytes=await readFile(join(folder,name));if(createHash('sha256').update(bytes).digest('hex')!==expected)throw Error('File hash mismatch; no import performed');
}
await mkdir(persist,{recursive:true});
const proxy=await getPlatformProxy({configPath:resolve('wrangler.current.jsonc'),persist:{path:persist},remoteBindings:false,envFiles:[]});
try{
  const db=proxy.env.DB;
  console.log(JSON.stringify({localOnly:true,phase:'checking-empty-target'}));
  const exists=await db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='companies'").first();
  if(exists)throw Error('Local test DB already initialized; refusing overwrite');
  const schema=await readFile(resolve('migrations-current/0001_current.sql'),'utf8');
  if(createHash('sha256').update(schema).digest('hex')!==manifest.migration_sha256)throw Error('Migration changed after snapshot');
  const ddl=unstable_splitSqlQuery(schema);
  for(let offset=0;offset<ddl.length;offset+=32)await db.batch(ddl.slice(offset,offset+32).map(sql=>db.prepare(sql)));
  console.log(JSON.stringify({localOnly:true,phase:'schema-created'}));
  let files=0;
  for(const name of manifest.data_files){
    const sql=await readFile(join(folder,name),'utf8');
    const queries=unstable_splitSqlQuery(sql);
    for(let offset=0;offset<queries.length;offset+=32)await db.batch(queries.slice(offset,offset+32).map(query=>db.prepare(query)));
    files++;if(files%25===0)console.log(JSON.stringify({localOnly:true,files,totalFiles:manifest.data_files.length}));
  }
  const counts={};
  for(const [table,expected]of Object.entries(manifest.expected_remote_counts||manifest.counts)){
    const escaped='"'+table.replaceAll('"','""')+'"';
    counts[table]=(await db.prepare('SELECT COUNT(*) n FROM '+escaped).first()).n;
    if(counts[table]!==expected)throw Error('Count mismatch in '+table);
  }
  const foreign=(await db.prepare('PRAGMA foreign_key_check').all()).results;
  const integrity=(await db.prepare('PRAGMA quick_check').all()).results;
  if(foreign.length||Object.values(integrity[0])[0]!=='ok')throw Error('D1 integrity check failed');
  console.log(JSON.stringify({localOnly:true,completed:true,tables:Object.keys(counts).length,counts,foreignKeyErrors:foreign.length,integrity:'ok'}));
}finally{await proxy.dispose();}
