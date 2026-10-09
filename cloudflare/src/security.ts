export interface SecurityEnv {
  DB: D1Database;
  SESSION_SECRET: string;
}

export interface SessionIdentity {
  accountId: string;
  username: string;
  expires: number;
}

const encoder = new TextEncoder();

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function hexToBytes(value: string): Uint8Array {
  if (!/^[0-9a-f]+$/i.test(value) || value.length % 2) throw new Error("hex inválido");
  return new Uint8Array(value.match(/.{2}/g)!.map((pair) => Number.parseInt(pair, 16)));
}

function base64UrlEncode(value: string): string {
  const bytes = encoder.encode(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(value: string): string {
  const normalized = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
  const binary = atob(padded);
  return new TextDecoder().decode(Uint8Array.from(binary, (character) => character.charCodeAt(0)));
}

async function hmacHex(secret: string, value: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return bytesToHex(new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(value))));
}

function constantTimeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

export async function verifyPassword(
  password: string,
  saltHex: string,
  expectedHex: string,
): Promise<boolean> {
  try {
    const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
    const derived = await crypto.subtle.deriveBits(
      { name: "PBKDF2", hash: "SHA-256", salt: hexToBytes(saltHex) as BufferSource, iterations: 260_000 },
      key,
      256,
    );
    return constantTimeEqual(bytesToHex(new Uint8Array(derived)), expectedHex.toLowerCase());
  } catch {
    return false;
  }
}

export async function hashPassword(password: string): Promise<{ salt: string; digest: string }> {
  const saltBytes = crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey("raw", encoder.encode(password), "PBKDF2", false, ["deriveBits"]);
  const derived = await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: "SHA-256", salt: saltBytes, iterations: 260_000 },
    key,
    256,
  );
  return { salt: bytesToHex(saltBytes), digest: bytesToHex(new Uint8Array(derived)) };
}

export async function createSessionCookie(
  secret: string,
  accountId: string,
  username: string,
): Promise<string> {
  const identity: SessionIdentity = {
    accountId,
    username,
    expires: Math.floor(Date.now() / 1000) + 12 * 60 * 60,
  };
  const payload = base64UrlEncode(JSON.stringify(identity));
  const signature = await hmacHex(secret, payload);
  return `radar_session=${payload}.${signature}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200`;
}

export function clearSessionCookie(): string {
  return "radar_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0";
}

function cookieValue(request: Request, name: string): string | null {
  const cookie = request.headers.get("Cookie") || "";
  for (const part of cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return rest.join("=");
  }
  return null;
}

export async function readSession(request: Request, env: SecurityEnv): Promise<SessionIdentity | null> {
  const token = cookieValue(request, "radar_session");
  if (!token || !env.SESSION_SECRET) return null;
  const separator = token.lastIndexOf(".");
  if (separator < 1) return null;
  const payload = token.slice(0, separator);
  const suppliedSignature = token.slice(separator + 1);
  const expectedSignature = await hmacHex(env.SESSION_SECRET, payload);
  if (!constantTimeEqual(suppliedSignature, expectedSignature)) return null;
  try {
    const identity = JSON.parse(base64UrlDecode(payload)) as SessionIdentity;
    if (!identity.accountId || !identity.username || identity.expires <= Math.floor(Date.now() / 1000)) return null;
    const account = await env.DB.prepare(
      "SELECT id, username FROM user_accounts WHERE id=? AND username=? COLLATE NOCASE AND is_active=1",
    ).bind(identity.accountId, identity.username).first<{ id: string; username: string }>();
    return account ? { ...identity, username: account.username } : null;
  } catch {
    return null;
  }
}

export function requestIsSameOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  if (!origin) return true;
  return origin === new URL(request.url).origin;
}
