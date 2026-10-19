/** Shared contracts for the current Radar API; no provider credentials here. */
export type Row = Record<string, unknown>;
export interface Principal {
  accountId: string;
  username: string;
  role: 'admin' | 'vendedor';
  expires: number;
  revision?: number;
}
export interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  SESSION_SECRET: string;
  RADAR_ALLOW_REGISTRATION: string;
  RADAR_ENV: string;
  RADAR_PUBLIC_URL?: string;
  RADAR_ADMIN_USER?: string;
  RADAR_REGISTRATION_CODE?: string;
  RECEITA_IMPORT_SECRET?: string;
  RECEITA_SYNC_AUTOMATION?: string;
}
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}
export function headers(source?: HeadersInit): Headers {
  const result = new Headers(source);
  result.set('X-Content-Type-Options', 'nosniff');
  result.set('X-Frame-Options', 'DENY');
  result.set('Referrer-Policy', 'same-origin');
  result.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()');
  result.set('Strict-Transport-Security', 'max-age=31536000');
  result.set('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https://brasilapi.com.br; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'");
  return result;
}
export function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {status, headers: headers({'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store'})});
}
export function now(): string {
  // Keep existing local business dates in Sao Paulo; never mix UTC-Z with naive history.
  const parts = new Intl.DateTimeFormat('sv-SE', {timeZone:'America/Sao_Paulo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date());
  return parts.replace(' ', 'T');
}
export async function bodyJson(request: Request, maximumBytes = 2 * 1024 * 1024): Promise<Row> {
  const length = request.headers.get('Content-Length');
  if (length && (!/^\d+$/.test(length) || Number(length) > maximumBytes)) throw new ApiError(413, 'Solicitação acima do limite permitido');
  if (!request.body) return {};
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = []; let size = 0;
  try {
    while (true) {
      const chunk = await reader.read(); if (chunk.done) break;
      size += chunk.value.byteLength;
      if (size > maximumBytes) { await reader.cancel(); throw new ApiError(413, 'Solicitação acima do limite permitido'); }
      chunks.push(chunk.value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try {
    const parsed: unknown = JSON.parse(new TextDecoder('utf-8', {fatal:true}).decode(bytes) || '{}');
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
    return parsed as Row;
  } catch { throw new ApiError(400, 'JSON inválido: informe um objeto'); }
}
export async function queryRows<T extends Row = Row>(db: D1Database, sql: string, values: unknown[] = []): Promise<T[]> {
  return (await db.prepare(sql).bind(...values).all<T>()).results || [];
}
export async function queryFirst<T extends Row = Row>(db: D1Database, sql: string, values: unknown[] = []): Promise<T | null> {
  return db.prepare(sql).bind(...values).first<T>();
}
export function privateCompanyVisible(alias: string, ownerExpression: string): string {
  return `(NOT (COALESCE(${alias}.uf,'')='ZZ' OR COALESCE(${alias}.situacao,'')='TESTE' OR EXISTS (SELECT 1 FROM private_companies identity WHERE identity.cnpj=${alias}.cnpj)) OR EXISTS (SELECT 1 FROM private_companies priv WHERE priv.cnpj=${alias}.cnpj AND priv.owner_id=${ownerExpression}))`;
}
export async function requireProfile(db: D1Database, profileId: string, principal: Principal): Promise<Row> {
  const profile = await queryFirst(db, 'SELECT * FROM sales_profiles WHERE id=? AND (?=1 OR owner_id=?)', [profileId, principal.role === 'admin' ? 1 : 0, principal.accountId]);
  if (!profile) throw new ApiError(404, 'Responsável não encontrado para esta conta');
  return profile;
}
export function moneyCents(value: unknown): number {
  if (typeof value === 'number' && Number.isInteger(value)) {
    if (!Number.isSafeInteger(value) || value < 0 || value > 100000000000000) throw new ApiError(400, 'Valor financeiro fora do intervalo permitido');
    return value;
  }
  if (value !== null && value !== undefined && typeof value !== 'string' && typeof value !== 'number') throw new ApiError(400, 'Valor financeiro inválido');
  const raw = String(value ?? '').trim().replace(/R\$| /g, '');
  if (!raw) return 0;
  const normalized = raw.includes(',') ? raw.replace(/\./g, '').replace(',', '.') : raw;
  const match = /^\+?(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(normalized);
  if (!match || !(match[1] || match[2]) || normalized.length > 200) throw new ApiError(400, 'Valor financeiro inválido');
  const exponent = Number(match[3] || 0);
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 100) throw new ApiError(400, 'Valor financeiro fora do intervalo permitido');
  let digits = (match[1] || '') + (match[2] || '');
  const decimalPosition = (match[1] || '').length + exponent;
  if (decimalPosition > 13 || decimalPosition < -100) throw new ApiError(400, 'Valor financeiro fora do intervalo permitido');
  if (decimalPosition < 0) digits = '0'.repeat(-decimalPosition) + digits;
  const point = Math.max(0, decimalPosition);
  digits = digits.padEnd(point + 3, '0');
  const amount = BigInt(digits.slice(0, point + 2) || '0');
  const max = 100000000000000n;
  // Check the unrounded amount as Python Decimal does, then ROUND_HALF_UP.
  if (amount > max || amount === max && /[1-9]/.test(digits.slice(point + 2))) throw new ApiError(400, 'Valor financeiro fora do intervalo permitido');
  return Number(amount + (digits[point + 2] >= '5' ? 1n : 0n));
}
