import { randomBytes, timingSafeEqual, createHmac } from 'node:crypto';
import { pbkdf2 } from '@noble/hashes/pbkdf2.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { ApiError } from './runtime';
import type { Env, Principal } from './runtime';

const iterations=260000;
async function derive(password:string,salt:string):Promise<string>{
  if(!/^[a-f\d]{32}$/i.test(salt))throw new Error('Salt inválido');
  // Production Workers cap the native PBKDF2 call at 100k; local workerd does not.
  // Use the same RFC 8018 algorithm/work factor, not weaker replacement hashes.
  const input=new TextEncoder().encode(password),saltBytes=Buffer.from(salt,'hex');
  let key:Uint8Array|undefined;
  try{key=pbkdf2(sha256,input,saltBytes,{c:iterations,dkLen:32});return Buffer.from(key).toString('hex');}
  finally{input.fill(0);saltBytes.fill(0);key?.fill(0);}
}
export async function hashPassword(password:string):Promise<{salt:string;digest:string}>{
  const salt=randomBytes(16).toString('hex');return {salt,digest:await derive(password,salt)};
}
export async function verifyPassword(password:string,salt:string,expected:string):Promise<boolean>{
  if(!/^[a-f\d]{64}$/i.test(expected)||!/^[a-f\d]{32}$/i.test(salt))return false;
  try{return timingSafeEqual(Buffer.from(await derive(password,salt),'hex'),Buffer.from(expected,'hex'));}
  catch{throw new ApiError(503,'Verificação de senha temporariamente indisponível');}
}
function signature(secret:string,payload:string):string{return createHmac('sha256',secret).update(payload).digest('hex');}
export async function createSessionCookie(secret:string,accountId:string,username:string,revision:number):Promise<string>{
  if(secret.length<32)throw new Error('Session secret must have at least 32 characters');
  const payload=Buffer.from(JSON.stringify({accountId,username,revision,expires:Math.floor(Date.now()/1000)+43200})).toString('base64url');
  return `radar_session=${payload}.${signature(secret,payload)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200`;
}
export function clearSessionCookie():string{return 'radar_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0';}
export async function readSession(request:Request,env:Pick<Env,'DB'|'SESSION_SECRET'>):Promise<Principal|null>{
  const tokens=(request.headers.get('Cookie')||'').split(';').map(s=>s.trim()).filter(s=>s.startsWith('radar_session='));
  if(tokens.length!==1||env.SESSION_SECRET.length<32)return null;
  const token=tokens[0].slice(14);if(token.length>2000)return null;
  const [payload,mac,...rest]=token.split('.');if(rest.length||!payload||!mac||!/^[a-f\d]{64}$/.test(mac))return null;
  if(!timingSafeEqual(Buffer.from(mac,'hex'),Buffer.from(signature(env.SESSION_SECRET,payload),'hex')))return null;
  try{
    const data=JSON.parse(Buffer.from(payload,'base64url').toString('utf8'));
    if(typeof data.accountId!=='string'||typeof data.username!=='string'||!Number.isInteger(data.revision)||!Number.isInteger(data.expires)||data.expires<=Date.now()/1000)return null;
    const account=await env.DB.prepare(`SELECT u.id,u.username,u.role,COALESCE(r.revision,0) revision FROM user_accounts u
      LEFT JOIN admin_session_revisions r ON r.username=u.username COLLATE NOCASE
      WHERE u.id=? AND u.username=? COLLATE NOCASE AND u.is_active=1`).bind(data.accountId,data.username).first<{id:string;username:string;role:string;revision:number}>();
    if(!account||account.revision!==data.revision)return null;
    return {accountId:account.id,username:account.username,expires:data.expires,revision:data.revision,role:['admin','administrador','gestor'].includes(String(account.role||'').trim().toLowerCase())?'admin':'vendedor'};
  }catch{return null;}
}
export async function revokeSession(db:D1Database,username:string):Promise<void>{
  await db.prepare(`INSERT INTO admin_session_revisions(username,revision) VALUES(?,1)
    ON CONFLICT(username) DO UPDATE SET revision=revision+1`).bind(username).run();
}
export function requestIsSameOrigin(request:Request):boolean{
  if(request.headers.get('Sec-Fetch-Site')==='cross-site')return false;
  const origin=request.headers.get('Origin');if(origin&&origin!==new URL(request.url).origin)return false;
  const referer=request.headers.get('Referer');
  if(!origin&&referer){try{return new URL(referer).origin===new URL(request.url).origin;}catch{return false;}}
  return true;
}
export async function consumeBudget(db:D1Database,key:string,maximum:number,seconds:number):Promise<boolean>{
  const stamp=Math.floor(Date.now()/1000);
  await db.prepare('DELETE FROM auth_attempts WHERE key IN (SELECT key FROM auth_attempts WHERE expires_at<=? LIMIT 50)').bind(stamp).run();
  const row=await db.prepare(`INSERT INTO auth_attempts(key,count,expires_at) VALUES(?,1,?)
    ON CONFLICT(key) DO UPDATE SET count=CASE WHEN expires_at<=? THEN 1 ELSE count+1 END,
    expires_at=CASE WHEN expires_at<=? THEN excluded.expires_at ELSE expires_at END RETURNING count`)
    .bind(key,stamp+seconds,stamp,stamp).first<{count:number}>();
  return Boolean(row&&row.count<=maximum);
}
