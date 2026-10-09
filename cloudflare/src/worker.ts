import {
  clearSessionCookie,
  createSessionCookie,
  readSession,
  requestIsSameOrigin,
  verifyPassword,
  type SessionIdentity,
} from "./security";
import {
  COMPANY_SELECT_SQL,
  COMPANY_SOURCE_SQL,
  LEAD_SCORE_SQL,
  companyFilters,
  integerParam,
  normalizeCnpj,
  scoreCompany,
} from "./query";

interface Env {
  DB: D1Database;
  ASSETS: Fetcher;
  SESSION_SECRET: string;
  RADAR_ALLOW_REGISTRATION: string;
  RADAR_ENV: string;
}

type Row = Record<string, unknown>;

const STAGES = new Set(["novo", "qualificado", "contatado", "negociacao", "convertido", "descartado"]);
const FILTER_FIELDS = new Set([
  "q", "inicio", "fim", "segmento", "cnae", "municipio", "regiao", "situacao",
  "mei", "contato", "lead_status", "favorito", "score_min",
  "cnae_include", "cnae_exclude", "name_terms", "name_exclude", "porte", "data_source", "phone_available", "email_available", "work_stage",
]);

function securityHeaders(headers = new Headers()): Headers {
  headers.set("X-Content-Type-Options", "nosniff");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Referrer-Policy", "same-origin");
  headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  headers.set("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
  return headers;
}

function json(data: unknown, status = 200, extraHeaders?: HeadersInit): Response {
  const headers = securityHeaders(new Headers(extraHeaders));
  headers.set("Content-Type", "application/json; charset=utf-8");
  headers.set("Cache-Control", "no-store");
  return new Response(JSON.stringify(data), { status, headers });
}

function redirect(location: string, cookie?: string): Response {
  const headers = securityHeaders(new Headers({ Location: location, "Cache-Control": "no-store" }));
  if (cookie) headers.append("Set-Cookie", cookie);
  return new Response(null, { status: 303, headers });
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function rows<T extends Row>(statement: D1PreparedStatement): Promise<T[]> {
  const result = await statement.all<T>();
  return result.results || [];
}

export async function boundedText(request: Request, maximumBytes = 65_536): Promise<string> {
  const length = Number(request.headers.get("Content-Length") || "0");
  if (length > maximumBytes) throw new Response(JSON.stringify({ erro: "Requisição muito grande" }), { status: 413 });
  if (!request.body) return "";
  const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      size += value.byteLength;
      if (size > maximumBytes) { await reader.cancel(); throw json({ erro: "Requisição muito grande" }, 413); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

async function bodyJson(request: Request, maximumBytes = 65_536): Promise<Row> {
  try {
    const parsed = JSON.parse(await boundedText(request, maximumBytes));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("objeto esperado");
    return parsed as Row;
  } catch (error) {
    if (error instanceof Response) throw error;
    throw new Response(JSON.stringify({ erro: "JSON inválido" }), { status: 400 });
  }
}

async function loginPage(request: Request, env: Env, mode = "login", error = "", values: Row = {}, status = 200): Promise<Response> {
  const assetUrl = new URL("/login.html", request.url);
  const asset = await env.ASSETS.fetch(new Request(assetUrl));
  if (!asset.ok) return new Response("Página de acesso indisponível", { status: 503 });
  const registrationEnabled = env.RADAR_ALLOW_REGISTRATION === "1";
  const view = mode === "register" && registrationEnabled ? "register" : "login";
  const message = error
    ? `<div class="auth-alert" role="alert"><span>!</span><p>${escapeHtml(error)}</p></div>`
    : "";
  let template = await asset.text();
  const replacements: Record<string, string> = {
    "__AUTH_VIEW__": view,
    "__REGISTRATION_STATE__": registrationEnabled ? "enabled" : "disabled",
    "<!--AUTH_ERROR-->": message,
    "__REGISTER_NAME__": escapeHtml(values.name),
    "__REGISTER_USERNAME__": escapeHtml(values.username),
    "__REGISTER_EMAIL__": escapeHtml(values.email),
  };
  for (const [marker, replacement] of Object.entries(replacements)) template = template.replaceAll(marker, replacement);
  const headers = securityHeaders(new Headers({
    "Content-Type": "text/html; charset=utf-8",
    "Cache-Control": "no-store",
  }));
  return new Response(template, { status, headers });
}

async function authenticate(request: Request, env: Env): Promise<SessionIdentity | Response> {
  const session = await readSession(request, env);
  if (session) return session;
  if (new URL(request.url).pathname.startsWith("/api/")) return json({ erro: "Autenticação necessária" }, 401);
  return redirect("/login");
}

function accountSourceStatement(env: Env, sql: string, accountId: string, values: unknown[] = []): D1PreparedStatement {
  return env.DB.prepare(sql).bind(accountId, ...values);
}

async function handleLogin(request: Request, env: Env): Promise<Response> {
  if (!requestIsSameOrigin(request)) return json({ erro: "Origem inválida" }, 403);
  if (!(request.headers.get('Content-Type') || '').startsWith('application/x-www-form-urlencoded')) return json({erro:'Formulário inválido'},415);
  const form = new URLSearchParams(await boundedText(request, 4096));
  const login = String(form.get("username") || "").trim().slice(0, 160);
  const password = String(form.get("password") || "").slice(0, 1024);
  const account = await env.DB.prepare(
    `SELECT id,username,password_hash,password_salt FROM user_accounts
     WHERE is_active=1 AND (username=? COLLATE NOCASE OR email=? COLLATE NOCASE) LIMIT 1`,
  ).bind(login, login).first<{ id: string; username: string; password_hash: string; password_salt: string }>();
  const principal = account ? 'account:' + account.id : 'unknown:' + login.toLowerCase();
  // CF-Connecting-IP is set by Cloudflare, never X-Forwarded-For. A separate
  // generous edge budget also bounds random-name sprays; no successful reset.
  const edge = account || await consumeLoginAttempt(env.DB, 'edge:' + (request.headers.get('CF-Connecting-IP') || 'local'), 1000);
  if (!edge) return loginPage(request,env,'login','Muitas tentativas. Aguarde 15 minutos.',{},429);
  const budget = await consumeLoginAttempt(env.DB, principal);
  if (!budget) return loginPage(request,env,'login','Muitas tentativas. Aguarde 15 minutos.',{},429);
  if (!account || !(await verifyPassword(password, account.password_salt, account.password_hash))) {
    return loginPage(request, env, "login", "Usuário, e-mail ou senha incorretos.", {}, 401);
  }
  const now = new Date().toISOString();
  await env.DB.prepare("UPDATE user_accounts SET last_login_at=?,updated_at=? WHERE id=?")
    .bind(now, now, account.id).run();
  await env.DB.prepare('DELETE FROM auth_attempts WHERE key=?').bind(principal).run();
  return redirect("/", await createSessionCookie(env.SESSION_SECRET, account.id, account.username));
}

async function consumeLoginAttempt(db: D1Database, key: string, maximum = 8): Promise<boolean> {
  const now = Math.floor(Date.now()/1000);
  await db.prepare('DELETE FROM auth_attempts WHERE key IN (SELECT key FROM auth_attempts WHERE expires_at<=? LIMIT 50)').bind(now).run();
  const row = await db.prepare(`INSERT INTO auth_attempts(key,count,expires_at) VALUES(?,1,?)
    ON CONFLICT(key) DO UPDATE SET count=CASE WHEN expires_at<=? THEN 1 ELSE count+1 END,
    expires_at=CASE WHEN expires_at<=? THEN excluded.expires_at ELSE expires_at END RETURNING count`)
    .bind(key, now+900, now, now).first<{count:number}>();
  return !!row && row.count<=maximum;
}

async function getCompanies(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const { where, values } = companyFilters(url.searchParams, new Set(), session.accountId);
  const page = integerParam(url.searchParams.get("page"), 1, 1, 1_000_000);
  const size = integerParam(url.searchParams.get("size"), 20, 1, 100);
  const totalRow = await accountSourceStatement(
    env,
    `SELECT COUNT(*) AS total FROM ${COMPANY_SOURCE_SQL} WHERE ${where}`,
    session.accountId,
    values,
  ).first<{ total: number }>();
  const companyRows = await accountSourceStatement(
    env,
    `SELECT ${COMPANY_SELECT_SQL} FROM ${COMPANY_SOURCE_SQL} WHERE ${where}
     ORDER BY COALESCE(acs.favorito,0) DESC,c.data_abertura DESC,c.id DESC LIMIT ? OFFSET ?`,
    session.accountId,
    [...values, size, (page - 1) * size],
  ).all<Row>();
  const items = (companyRows.results || []).map((item) => ({ ...item, lead_score: scoreCompany(item) }));
  return json({ items, total: Number(totalRow?.total || 0), page, size });
}

async function getProfiles(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const profileRows = await rows<Row>(env.DB.prepare(
    `SELECT * FROM prospecting_profiles
     WHERE is_system=1 OR owner_id=? ORDER BY is_system DESC,created_at,name`,
  ).bind(session.accountId));
  const items: Row[] = [];
  for (const profile of profileRows) {
    let filters: Record<string, string> = {};
    try { filters = JSON.parse(String(profile.filters_json || "{}")); } catch { filters = {}; }
    const params = new URLSearchParams(filters);
    const { where, values } = companyFilters(params, new Set(), session.accountId);
    const companyCount = await accountSourceStatement(
      env,
      `SELECT COUNT(*) AS total FROM ${COMPANY_SOURCE_SQL} WHERE ${where}`,
      session.accountId,
      values,
    ).first<{ total: number }>();
    const leadCount = await env.DB.prepare(
      "SELECT COUNT(*) AS total FROM profile_leads WHERE owner_id=? AND profile_id=?",
    ).bind(session.accountId, profile.id).first<{ total: number }>();
    const { filters_json: _filtersJson, owner_id: _ownerId, ...safeProfile } = profile;
    items.push({ ...safeProfile, filters, companies: Number(companyCount?.total || 0), lead_count: Number(leadCount?.total || 0) });
  }
  return json({ items });
}

async function getStats(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const filters = companyFilters(url.searchParams, new Set(), session.accountId);
  const meiFilters = companyFilters(url.searchParams, new Set(["mei", "lead_status", "favorito"]), session.accountId);
  const opportunityFilters = companyFilters(url.searchParams, new Set(["score_min", "lead_status", "favorito"]), session.accountId);
  const bind = (sql: string, filter = filters) => accountSourceStatement(
    env,
    sql,
    session.accountId,
    filter.values,
  );
  const summary = await bind(
    `SELECT COUNT(*) total,COALESCE(SUM(c.mei),0) meis,COUNT(DISTINCT c.municipio) municipios,
     COUNT(DISTINCT c.segmento) segmentos,
     COALESCE(SUM(CASE WHEN TRIM(COALESCE(c.email,''))<>'' OR TRIM(COALESCE(c.telefone,''))<>'' THEN 1 ELSE 0 END),0) com_contato,
     MAX(c.data_abertura) ultima_data FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where}`,
  ).first<Row>() || {};
  const [groups, cnaes, cities, timeline, pipeline] = await Promise.all([
    rows<Row>(bind(`SELECT c.segmento label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where} GROUP BY c.segmento ORDER BY value DESC LIMIT 6`)),
    rows<Row>(bind(`SELECT c.cnae label,MAX(c.cnae_descricao) description,c.segmento category,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where} AND c.cnae<>'' GROUP BY c.cnae,c.segmento ORDER BY value DESC,c.cnae LIMIT 8`)),
    rows<Row>(bind(`SELECT c.municipio label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where} GROUP BY c.municipio ORDER BY value DESC,c.municipio LIMIT 5`)),
    rows<Row>(bind(`SELECT substr(c.data_abertura,1,7) label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where} AND c.data_abertura<>'' GROUP BY substr(c.data_abertura,1,7) ORDER BY label`)),
    rows<Row>(bind(`SELECT COALESCE(acs.lead_status,'novo') label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where} GROUP BY COALESCE(acs.lead_status,'novo')`)),
  ]);
  const favoriteRow = await bind(
    `SELECT COUNT(*) total FROM ${COMPANY_SOURCE_SQL} WHERE ${filters.where} AND COALESCE(acs.favorito,0)=1`,
  ).first<{ total: number }>();
  const meiSummary = await bind(
    `SELECT COUNT(*) total,COUNT(DISTINCT c.cnae) cnaes,COUNT(DISTINCT c.municipio) municipios,MAX(c.data_abertura) ultima_data
     FROM ${COMPANY_SOURCE_SQL} WHERE ${meiFilters.where} AND c.mei=1`,
    meiFilters,
  ).first<Row>() || {};
  const [meiCnaes, meiGroups, meiCities, meiTimeline] = await Promise.all([
    rows<Row>(bind(`SELECT c.cnae label,MAX(c.cnae_descricao) description,c.segmento category,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${meiFilters.where} AND c.mei=1 AND c.cnae<>'' GROUP BY c.cnae,c.segmento ORDER BY value DESC,c.cnae LIMIT 10`, meiFilters)),
    rows<Row>(bind(`SELECT c.segmento label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${meiFilters.where} AND c.mei=1 AND c.segmento<>'' GROUP BY c.segmento ORDER BY value DESC,c.segmento LIMIT 6`, meiFilters)),
    rows<Row>(bind(`SELECT c.municipio label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${meiFilters.where} AND c.mei=1 AND c.municipio<>'' GROUP BY c.municipio ORDER BY value DESC,c.municipio LIMIT 5`, meiFilters)),
    rows<Row>(bind(`SELECT substr(c.data_abertura,1,7) label,COUNT(*) value FROM ${COMPANY_SOURCE_SQL} WHERE ${meiFilters.where} AND c.mei=1 AND c.data_abertura<>'' GROUP BY substr(c.data_abertura,1,7) ORDER BY label`, meiFilters)),
  ]);
  const baseDate = await env.DB.prepare("SELECT MAX(data_abertura) value FROM companies WHERE uf='RS'").first<{ value: string }>();
  summary.base_ultima_data = baseDate?.value || null;
  const optionRows = await rows<{ kind: string; value: string }>(env.DB.prepare("SELECT kind,value FROM filter_options ORDER BY kind,value"));
  const options: Record<string, unknown> = { municipio: [], regiao: [], segmento: [] };
  for (const option of optionRows) (options[option.kind] as string[] | undefined)?.push(option.value);
  options.cnaes = await rows<Row>(env.DB.prepare(
    "SELECT codigo,descricao,segmento,empresas FROM cnae_catalog ORDER BY empresas DESC,codigo LIMIT 1500",
  ));
  for (const key of ["porte", "data_source"]) {
    options[key] = (await rows<{ value: string }>(env.DB.prepare(`SELECT DISTINCT ${key} value FROM companies WHERE ${key}<>'' ORDER BY ${key}`))).map(row => row.value);
  }
  const highWhere = `${opportunityFilters.where} AND ${LEAD_SCORE_SQL}>=80`;
  const highTotal = await bind(`SELECT COUNT(*) total FROM ${COMPANY_SOURCE_SQL} WHERE ${highWhere}`, opportunityFilters).first<{ total: number }>();
  const highContact = await bind(`SELECT COUNT(*) total FROM ${COMPANY_SOURCE_SQL} WHERE ${highWhere} AND (TRIM(COALESCE(c.email,''))<>'' OR TRIM(COALESCE(c.telefone,''))<>'')`, opportunityFilters).first<{ total: number }>();
  const highMei = await bind(`SELECT COUNT(*) total FROM ${COMPANY_SOURCE_SQL} WHERE ${highWhere} AND c.mei=1`, opportunityFilters).first<{ total: number }>();
  const highRows = await rows<Row>(bind(
    `SELECT ${COMPANY_SELECT_SQL} FROM ${COMPANY_SOURCE_SQL} WHERE ${highWhere}
     ORDER BY ${LEAD_SCORE_SQL} DESC,c.data_abertura DESC,c.id DESC LIMIT 8`,
    opportunityFilters,
  ));
  const highItems = highRows.map((item) => ({ ...item, lead_score: scoreCompany(item) }));
  return json({
    summary,
    groups,
    cnaes,
    cities,
    timeline,
    pipeline,
    favorites: Number(favoriteRow?.total || 0),
    options,
    mei_summary: meiSummary,
    mei_cnaes: meiCnaes,
    mei_groups: meiGroups,
    mei_cities: meiCities,
    mei_timeline: meiTimeline,
    opportunities: {
      total: Number(highTotal?.total || 0),
      with_contact: Number(highContact?.total || 0),
      mei: Number(highMei?.total || 0),
      items: highItems,
    },
  });
}

async function getProfileLeads(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const profileId = (url.searchParams.get("profile_id") || "").trim();
  if (!profileId) return json({ erro: "Selecione um perfil" }, 400);
  const page = integerParam(url.searchParams.get("page"), 1, 1, 1_000_000);
  const size = integerParam(url.searchParams.get("size"), 24, 1, 100);
  const profile = await env.DB.prepare(
    "SELECT id,name,is_system FROM prospecting_profiles WHERE id=? AND (is_system=1 OR owner_id=?)",
  ).bind(profileId, session.accountId).first<Row>();
  if (!profile) return json({ erro: "Perfil não encontrado" }, 404);
  const count = await env.DB.prepare(
    "SELECT COUNT(*) total FROM profile_leads WHERE owner_id=? AND profile_id=?",
  ).bind(session.accountId, profileId).first<{ total: number }>();
  const result = await env.DB.prepare(
    `SELECT ${COMPANY_SELECT_SQL},pl.added_at AS carteira_adicionado_em
     FROM profile_leads pl
     JOIN companies c ON c.cnpj=pl.cnpj
     LEFT JOIN account_company_state acs ON acs.cnpj=c.cnpj AND acs.owner_id=pl.owner_id
     WHERE pl.owner_id=? AND pl.profile_id=?
     ORDER BY COALESCE(acs.favorito,0) DESC,c.data_abertura DESC,pl.added_at DESC
     LIMIT ? OFFSET ?`,
  ).bind(session.accountId, profileId, size, (page - 1) * size).all<Row>();
  const items = (result.results || []).map((item) => ({ ...item, lead_score: scoreCompany(item) }));
  return json({ profile, items, total: Number(count?.total || 0), page, size });
}

async function getProfileMemberships(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const cnpj = normalizeCnpj(url.searchParams.get("cnpj"));
  if (cnpj.length !== 14) return json({ erro: "CNPJ inválido" }, 400);
  const items = await rows<Row>(env.DB.prepare(
    `SELECT p.id,p.name,p.description,p.is_system,
     CASE WHEN pl.cnpj IS NULL THEN 0 ELSE 1 END AS selected
     FROM prospecting_profiles p
     LEFT JOIN profile_leads pl ON pl.owner_id=? AND pl.profile_id=p.id AND pl.cnpj=?
     WHERE p.is_system=0 AND p.owner_id=? ORDER BY p.name`,
  ).bind(session.accountId, cnpj, session.accountId));
  return json({ items });
}

async function getTeamProfiles(env: Env, session: SessionIdentity): Promise<Response> {
  const items = await rows<Row>(env.DB.prepare(
    `SELECT p.*,COUNT(spl.cnpj) AS lead_count,
     COALESCE(SUM(CASE WHEN spl.favorito=1 THEN 1 ELSE 0 END),0) AS favorite_count,
     MAX(spl.updated_at) AS last_activity
     FROM sales_profiles p
     LEFT JOIN sales_profile_leads spl ON spl.owner_id=p.owner_id AND spl.profile_id=p.id
     WHERE p.owner_id=? GROUP BY p.id ORDER BY p.name COLLATE NOCASE`,
  ).bind(session.accountId));
  return json({ items: items.map(({ owner_id: _ownerId, ...item }) => item) });
}

function teamLeadConditions(url: URL): { condition: string; values: unknown[]; view: string; status: string } | Response {
  const profileId = (url.searchParams.get("profile_id") || "").trim();
  if (!profileId) return json({ erro: "Selecione um perfil individual" }, 400);
  const view = (url.searchParams.get("view") || "all").trim().toLowerCase() === "favorites" ? "favorites" : "all";
  const status = (url.searchParams.get("status") || "").trim().toLowerCase();
  if (status && !STAGES.has(status)) return json({ erro: "Etapa inválida" }, 400);
  const clauses = ["spl.owner_id=?", "spl.profile_id=?"];
  const values: unknown[] = [profileId];
  if (view === "favorites") clauses.push("spl.favorito=1");
  if (status) { clauses.push("spl.lead_status=?"); values.push(status); }
  return { condition: clauses.join(" AND "), values, view, status };
}

async function getTeamLeads(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const parsed = teamLeadConditions(url);
  if (parsed instanceof Response) return parsed;
  const profileId = String(parsed.values[0]);
  const profile = await env.DB.prepare("SELECT * FROM sales_profiles WHERE id=? AND owner_id=?")
    .bind(profileId, session.accountId).first<Row>();
  if (!profile) return json({ erro: "Perfil individual não encontrado" }, 404);
  const page = integerParam(url.searchParams.get("page"), 1, 1, 1_000_000);
  const size = integerParam(url.searchParams.get("size"), 24, 1, 100);
  const bindings = [session.accountId, ...parsed.values];
  const count = await env.DB.prepare(`SELECT COUNT(*) total FROM sales_profile_leads spl WHERE ${parsed.condition}`)
    .bind(...bindings).first<{ total: number }>();
  const result = await env.DB.prepare(
    `SELECT c.*,spl.profile_id,spl.added_at AS carteira_adicionado_em,
     spl.updated_at AS profile_updated_at,spl.favorito AS profile_favorito,
     spl.lead_status AS profile_lead_status,spl.observacoes AS profile_observacoes,
     spl.estrategia AS profile_estrategia
     FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
     WHERE ${parsed.condition}
     ORDER BY spl.favorito DESC,spl.updated_at DESC,c.data_abertura DESC,c.id DESC LIMIT ? OFFSET ?`,
  ).bind(...bindings, size, (page - 1) * size).all<Row>();
  const items = (result.results || []).map((item) => ({ ...item, lead_score: scoreCompany(item) }));
  const { owner_id: _ownerId, ...safeProfile } = profile;
  return json({ profile: safeProfile, items, total: Number(count?.total || 0), page, size, view: parsed.view, status: parsed.status });
}

async function getTeamMemberships(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const cnpj = normalizeCnpj(url.searchParams.get("cnpj"));
  if (cnpj.length !== 14) return json({ erro: "CNPJ inválido" }, 400);
  const items = await rows<Row>(env.DB.prepare(
    `SELECT p.id,p.name,p.role,p.email,p.initials,p.color,
     CASE WHEN spl.cnpj IS NULL THEN 0 ELSE 1 END AS selected,
     COALESCE(spl.favorito,0) AS favorito,COALESCE(spl.lead_status,'novo') AS lead_status,
     COALESCE(spl.observacoes,'') AS observacoes,COALESCE(spl.estrategia,'') AS estrategia,
     spl.updated_at
     FROM sales_profiles p
     LEFT JOIN sales_profile_leads spl ON spl.owner_id=p.owner_id AND spl.profile_id=p.id AND spl.cnpj=?
     WHERE p.owner_id=? ORDER BY p.name COLLATE NOCASE`,
  ).bind(cnpj, session.accountId));
  return json({ items });
}

function csvCell(value: unknown): string {
  let text = String(value ?? "");
  if (typeof value === 'string' && /^(?:[\t\r\n]|[\s\ufeff]*[=+\-@])/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

async function getTeamLeadsCsv(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const parsed = teamLeadConditions(url);
  if (parsed instanceof Response) return parsed;
  const profileId = String(parsed.values[0]);
  const profile = await env.DB.prepare("SELECT name FROM sales_profiles WHERE id=? AND owner_id=?")
    .bind(profileId, session.accountId).first<{ name: string }>();
  if (!profile) return json({ erro: "Perfil individual não encontrado" }, 404);
  const result = await env.DB.prepare(
    `SELECT c.*,spl.favorito AS profile_favorito,spl.lead_status AS profile_lead_status,
     spl.observacoes AS profile_observacoes,spl.estrategia AS profile_estrategia
     FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
     WHERE ${parsed.condition} ORDER BY spl.favorito DESC,spl.updated_at DESC,c.data_abertura DESC`,
  ).bind(session.accountId, ...parsed.values).all<Row>();
  const headings = ["Empresa", "CNPJ", "Data de abertura", "CNAE", "Descrição do CNAE", "Segmento", "Município", "Região", "Situação", "Telefone", "E-mail", "Potencial", "Favorito", "Etapa", "Observações", "Estratégia"];
  const lines = [headings.map(csvCell).join(";")];
  for (const item of result.results || []) {
    lines.push([
      item.nome_fantasia || item.razao_social,
      item.cnpj,
      item.data_abertura,
      item.cnae,
      item.cnae_descricao,
      item.segmento,
      item.municipio,
      item.regiao,
      item.situacao,
      item.telefone,
      item.email,
      scoreCompany(item),
      item.profile_favorito ? "Sim" : "Não",
      item.profile_lead_status || "novo",
      item.profile_observacoes,
      item.profile_estrategia,
    ].map(csvCell).join(";"));
  }
  const safeName = profile.name.normalize("NFKD").replace(/[^\p{L}\p{N} _-]/gu, "").trim().replace(/\s+/g, "-").toLowerCase() || "perfil";
  const headers = securityHeaders(new Headers({
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": `attachment; filename="radar-${safeName}-leads.csv"`,
    "Cache-Control": "no-store",
  }));
  return new Response(`\ufeff${lines.join("\n")}\n`, { headers });
}

async function getSyncState(env: Env): Promise<Response> {
  const metaRows = await rows<{ key: string; value: string }>(env.DB.prepare("SELECT key,value FROM sync_meta"));
  const local = Object.fromEntries(metaRows.map((row) => [row.key, row.value]));
  if (local.competencia) {
    return json({ status: "complete", fase: "Base oficial publicada no D1", progresso: 100, competencia: local.competencia, mensagem: `Competência ${local.competencia} disponível`, local });
  }
  return json({ status: "idle", fase: "Aguardando importação validada", progresso: 0, mensagem: "A base Cloudflare ainda não foi promovida para produção.", local });
}

function getMonitorState(): Response {
  return json({
    status: "disabled",
    configurado: false,
    fase: "Monitor Cloudflare ainda não promovido",
    mensagem: "A sincronização agendada será habilitada depois da validação da base e dos segredos Serpro.",
    progresso: 0,
  });
}

async function createTeamProfile(request: Request, env: Env, session: SessionIdentity): Promise<Response> {
  const payload = await bodyJson(request, 16_384);
  const name = String(payload.name || "").trim().slice(0, 80);
  const role = String(payload.role || "Vendedor").trim().slice(0, 80) || "Vendedor";
  const email = String(payload.email || "").trim().slice(0, 160);
  if (!name) return json({ erro: "Informe o nome do perfil" }, 400);
  const initials = name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase().slice(0, 2) || "R";
  const id = `usuario-${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO sales_profiles(id,owner_id,name,role,email,initials,color,created_at,updated_at)
     VALUES(?,?,?,?,?,?,?,?,?)`,
  ).bind(id, session.accountId, name, role, email, initials, "#b82043", now, now).run();
  return json({ id, name, role, email, initials, color: "#b82043", lead_count: 0, favorite_count: 0 }, 201);
}

async function addTeamLead(request: Request, env: Env, session: SessionIdentity): Promise<Response> {
  const payload = await bodyJson(request, 32_768);
  const profileId = String(payload.profile_id || "").trim();
  const cnpj = normalizeCnpj(payload.cnpj);
  if (!profileId || cnpj.length !== 14) return json({ erro: "Perfil ou CNPJ inválido" }, 400);
  const profile = await env.DB.prepare("SELECT id FROM sales_profiles WHERE id=? AND owner_id=?")
    .bind(profileId, session.accountId).first();
  if (!profile) return json({ erro: "Perfil individual não encontrado" }, 404);
  const company = await env.DB.prepare("SELECT cnpj FROM companies WHERE cnpj=?").bind(cnpj).first();
  if (!company) return json({ erro: "Empresa não encontrada" }, 404);
  const now = new Date().toISOString();
  const existing = await env.DB.prepare(
    "SELECT 1 found FROM sales_profile_leads WHERE owner_id=? AND profile_id=? AND cnpj=?",
  ).bind(session.accountId, profileId, cnpj).first();
  if (existing) {
    await env.DB.prepare(
      "UPDATE sales_profile_leads SET updated_at=? WHERE owner_id=? AND profile_id=? AND cnpj=?",
    ).bind(now, session.accountId, profileId, cnpj).run();
  } else {
    await env.DB.prepare(
      `INSERT INTO sales_profile_leads(owner_id,profile_id,cnpj,added_at,updated_at)
       VALUES(?,?,?,?,?)`,
    ).bind(session.accountId, profileId, cnpj, now, now).run();
  }
  await env.DB.prepare("UPDATE sales_profiles SET updated_at=? WHERE id=? AND owner_id=?")
    .bind(now, profileId, session.accountId).run();
  const count = await env.DB.prepare(
    "SELECT COUNT(*) total FROM sales_profile_leads WHERE owner_id=? AND profile_id=?",
  ).bind(session.accountId, profileId).first<{ total: number }>();
  return json({ adicionado: !existing, profile_id: profileId, cnpj, lead_count: Number(count?.total || 0) }, existing ? 200 : 201);
}

async function createProfile(request: Request, env: Env, session: SessionIdentity): Promise<Response> {
  const payload = await bodyJson(request);
  const name = String(payload.name || "").trim().slice(0, 60);
  const description = String(payload.description || "").trim().slice(0, 180);
  if (!name) return json({ erro: "Informe o nome do perfil" }, 400);
  if (!payload.filters || typeof payload.filters !== "object" || Array.isArray(payload.filters)) return json({ erro: "Filtros do perfil inválidos" }, 400);
  const cleanFilters: Record<string, string> = {};
  for (const [key, value] of Object.entries(payload.filters as Row)) {
    const normalized = String(value || "").trim().slice(0, 1000);
    if (FILTER_FIELDS.has(key) && normalized) cleanFilters[key] = normalized;
  }
  const id = `perfil-${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO prospecting_profiles(id,owner_id,name,description,filters_json,is_system,created_at,updated_at)
     VALUES(?,?,?,?,?,0,?,?)`,
  ).bind(id, session.accountId, name, description, JSON.stringify(cleanFilters), now, now).run();
  return json({ id, name, description, filters: cleanFilters, is_system: 0, companies: 0, lead_count: 0 }, 201);
}

async function addProfileLead(request: Request, env: Env, session: SessionIdentity): Promise<Response> {
  const payload = await bodyJson(request, 16_384);
  const profileId = String(payload.profile_id || "").trim();
  const cnpj = normalizeCnpj(payload.cnpj);
  if (!profileId || cnpj.length !== 14) return json({ erro: "Perfil ou CNPJ inválido" }, 400);
  const profile = await env.DB.prepare(
    "SELECT id FROM prospecting_profiles WHERE id=? AND owner_id=? AND is_system=0",
  ).bind(profileId, session.accountId).first();
  if (!profile) return json({ erro: "Perfil personalizado não encontrado" }, 404);
  if (!(await env.DB.prepare("SELECT cnpj FROM companies WHERE cnpj=?").bind(cnpj).first())) return json({ erro: "Empresa não encontrada" }, 404);
  const existing = await env.DB.prepare(
    "SELECT 1 found FROM profile_leads WHERE owner_id=? AND profile_id=? AND cnpj=?",
  ).bind(session.accountId, profileId, cnpj).first();
  if (!existing) {
    await env.DB.prepare("INSERT INTO profile_leads(owner_id,profile_id,cnpj,added_at) VALUES(?,?,?,?)")
      .bind(session.accountId, profileId, cnpj, new Date().toISOString()).run();
  }
  const count = await env.DB.prepare("SELECT COUNT(*) total FROM profile_leads WHERE owner_id=? AND profile_id=?")
    .bind(session.accountId, profileId).first<{ total: number }>();
  return json({ adicionado: !existing, profile_id: profileId, cnpj, lead_count: Number(count?.total || 0) }, existing ? 200 : 201);
}

async function updateTeamLead(request: Request, env: Env, session: SessionIdentity): Promise<Response> {
  const payload = await bodyJson(request);
  const profileId = String(payload.profile_id || "").trim();
  const cnpj = normalizeCnpj(payload.cnpj);
  if (!profileId || cnpj.length !== 14) return json({ erro: "Perfil ou CNPJ inválido" }, 400);
  const assignments: string[] = [];
  const values: unknown[] = [];
  if (Object.hasOwn(payload, "lead_status")) {
    const stage = String(payload.lead_status || "");
    if (!STAGES.has(stage)) return json({ erro: "Etapa inválida" }, 400);
    assignments.push("lead_status=?"); values.push(stage);
  }
  if (Object.hasOwn(payload, "favorito")) { assignments.push("favorito=?"); values.push(payload.favorito ? 1 : 0); }
  if (Object.hasOwn(payload, "observacoes")) { assignments.push("observacoes=?"); values.push(String(payload.observacoes || "").slice(0, 4000)); }
  if (Object.hasOwn(payload, "estrategia")) { assignments.push("estrategia=?"); values.push(String(payload.estrategia || "").slice(0, 4000)); }
  if (!assignments.length) return json({ erro: "Nenhuma alteração válida" }, 400);
  const profile = await env.DB.prepare("SELECT id FROM sales_profiles WHERE id=? AND owner_id=?")
    .bind(profileId, session.accountId).first();
  if (!profile) return json({ erro: "Perfil individual não encontrado" }, 404);
  const lead = await env.DB.prepare(
    "SELECT 1 found FROM sales_profile_leads WHERE owner_id=? AND profile_id=? AND cnpj=?",
  ).bind(session.accountId, profileId, cnpj).first();
  if (!lead) return json({ erro: "Adicione o lead à carteira antes de editar" }, 404);
  const now = new Date().toISOString();
  assignments.push("updated_at=?"); values.push(now);
  await env.DB.prepare(
    `UPDATE sales_profile_leads SET ${assignments.join(",")}
     WHERE owner_id=? AND profile_id=? AND cnpj=?`,
  ).bind(...values, session.accountId, profileId, cnpj).run();
  await env.DB.prepare("UPDATE sales_profiles SET updated_at=? WHERE id=? AND owner_id=?")
    .bind(now, profileId, session.accountId).run();
  const item = await env.DB.prepare(
    `SELECT c.*,spl.profile_id,spl.updated_at AS profile_updated_at,
     spl.favorito AS profile_favorito,spl.lead_status AS profile_lead_status,
     spl.observacoes AS profile_observacoes,spl.estrategia AS profile_estrategia
     FROM sales_profile_leads spl JOIN companies c ON c.cnpj=spl.cnpj
     WHERE spl.owner_id=? AND spl.profile_id=? AND spl.cnpj=?`,
  ).bind(session.accountId, profileId, cnpj).first<Row>();
  return json({ ...item, lead_score: scoreCompany(item || {}) });
}

async function updateAccountLead(request: Request, url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const cnpj = normalizeCnpj(url.pathname.split("/").at(-1));
  if (cnpj.length !== 14) return json({ erro: "CNPJ inválido" }, 400);
  if (!(await env.DB.prepare("SELECT cnpj FROM companies WHERE cnpj=?").bind(cnpj).first())) return json({ erro: "Empresa não encontrada" }, 404);
  const payload = await bodyJson(request);
  const stage = Object.hasOwn(payload, "lead_status") ? String(payload.lead_status || "") : "novo";
  if (Object.hasOwn(payload, "lead_status") && !STAGES.has(stage)) return json({ erro: "Etapa inválida" }, 400);
  const current = await env.DB.prepare(
    "SELECT lead_status,favorito,observacoes FROM account_company_state WHERE owner_id=? AND cnpj=?",
  ).bind(session.accountId, cnpj).first<{ lead_status: string; favorito: number; observacoes: string }>();
  if (!current && !Object.keys(payload).some((key) => ["lead_status", "favorito", "observacoes"].includes(key))) {
    return json({ erro: "Nenhuma alteração válida" }, 400);
  }
  const nextStage = Object.hasOwn(payload, "lead_status") ? stage : current?.lead_status || "novo";
  const favorite = Object.hasOwn(payload, "favorito") ? (payload.favorito ? 1 : 0) : current?.favorito || 0;
  const notes = Object.hasOwn(payload, "observacoes") ? String(payload.observacoes || "").slice(0, 4000) : current?.observacoes || "";
  const now = new Date().toISOString();
  await env.DB.prepare(
    `INSERT INTO account_company_state(owner_id,cnpj,lead_status,favorito,observacoes,updated_at)
     VALUES(?,?,?,?,?,?)
     ON CONFLICT(owner_id,cnpj) DO UPDATE SET
       lead_status=excluded.lead_status,favorito=excluded.favorito,
       observacoes=excluded.observacoes,updated_at=excluded.updated_at`,
  ).bind(session.accountId, cnpj, nextStage, favorite, notes, now).run();
  const item = await env.DB.prepare(
    `SELECT ${COMPANY_SELECT_SQL} FROM ${COMPANY_SOURCE_SQL} WHERE c.cnpj=?`,
  ).bind(session.accountId, cnpj).first<Row>();
  return json({ ...item, lead_score: scoreCompany(item || {}) });
}

async function deleteTeamLead(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const profileId = (url.searchParams.get("profile_id") || "").trim();
  const cnpj = normalizeCnpj(url.searchParams.get("cnpj"));
  if (!profileId || cnpj.length !== 14) return json({ erro: "Perfil ou CNPJ inválido" }, 400);
  const result = await env.DB.prepare(
    "DELETE FROM sales_profile_leads WHERE owner_id=? AND profile_id=? AND cnpj=?",
  ).bind(session.accountId, profileId, cnpj).run();
  return json({ removido: Number(result.meta.changes || 0) > 0, profile_id: profileId, cnpj });
}

async function deleteTeamProfile(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const profileId = decodeURIComponent(url.pathname.split("/").at(-1) || "");
  const result = await env.DB.prepare("DELETE FROM sales_profiles WHERE id=? AND owner_id=?")
    .bind(profileId, session.accountId).run();
  if (!result.meta.changes) return json({ erro: "Perfil individual não encontrado" }, 404);
  return json({ excluido: true });
}

async function deleteProfileLead(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const profileId = (url.searchParams.get("profile_id") || "").trim();
  const cnpj = normalizeCnpj(url.searchParams.get("cnpj"));
  if (!profileId || cnpj.length !== 14) return json({ erro: "Perfil ou CNPJ inválido" }, 400);
  const result = await env.DB.prepare(
    "DELETE FROM profile_leads WHERE owner_id=? AND profile_id=? AND cnpj=?",
  ).bind(session.accountId, profileId, cnpj).run();
  return json({ removido: Number(result.meta.changes || 0) > 0, profile_id: profileId, cnpj });
}

async function deleteProfile(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  const profileId = decodeURIComponent(url.pathname.split("/").at(-1) || "");
  const profile = await env.DB.prepare(
    "SELECT is_system FROM prospecting_profiles WHERE id=? AND (is_system=1 OR owner_id=?)",
  ).bind(profileId, session.accountId).first<{ is_system: number }>();
  if (!profile) return json({ erro: "Perfil não encontrado" }, 404);
  if (profile.is_system) return json({ erro: "Perfis do sistema não podem ser excluídos" }, 400);
  await env.DB.prepare("DELETE FROM prospecting_profiles WHERE id=? AND owner_id=?")
    .bind(profileId, session.accountId).run();
  return json({ excluido: true });
}

async function apiGet(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  switch (url.pathname) {
    case "/api/companies": return getCompanies(url, env, session);
    case "/api/stats": return getStats(url, env, session);
    case "/api/profiles": return getProfiles(url, env, session);
    case "/api/profile-leads": return getProfileLeads(url, env, session);
    case "/api/profile-memberships": return getProfileMemberships(url, env, session);
    case "/api/team-profiles": return getTeamProfiles(env, session);
    case "/api/team-leads": return getTeamLeads(url, env, session);
    case "/api/team-memberships": return getTeamMemberships(url, env, session);
    case "/api/team-leads.csv": return getTeamLeadsCsv(url, env, session);
    case "/api/sync": return getSyncState(env);
    case "/api/monitor": return getMonitorState();
    default: return json({ erro: "Rota não encontrada" }, 404);
  }
}

async function apiPost(request: Request, url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  switch (url.pathname) {
    case "/api/team-profiles": return createTeamProfile(request, env, session);
    case "/api/team-leads": return addTeamLead(request, env, session);
    case "/api/profiles": return createProfile(request, env, session);
    case "/api/profile-leads": return addProfileLead(request, env, session);
    case "/api/sync": return json({ erro: "A sincronização Cloudflare será habilitada após a validação da migração." }, 409);
    case "/api/monitor": return json({ erro: "O monitor Cloudflare ainda não possui credenciais Serpro." }, 409);
    default: return json({ erro: "Rota não encontrada" }, 404);
  }
}

async function apiPut(request: Request, url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  if (url.pathname === "/api/team-leads") return updateTeamLead(request, env, session);
  if (url.pathname.startsWith("/api/leads/")) return updateAccountLead(request, url, env, session);
  return json({ erro: "Rota não encontrada" }, 404);
}

async function apiDelete(url: URL, env: Env, session: SessionIdentity): Promise<Response> {
  if (url.pathname === "/api/team-leads") return deleteTeamLead(url, env, session);
  if (url.pathname.startsWith("/api/team-profiles/")) return deleteTeamProfile(url, env, session);
  if (url.pathname === "/api/profile-leads") return deleteProfileLead(url, env, session);
  if (url.pathname.startsWith("/api/profiles/")) return deleteProfile(url, env, session);
  return json({ erro: "Rota não encontrada" }, 404);
}

function withSecurityHeaders(response: Response): Response {
  const headers = securityHeaders(new Headers(response.headers));
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

async function handleRequest(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  if (url.pathname === "/healthz") {
    try {
      await env.DB.prepare("SELECT 1").first();
      return json({ status: "ok", environment: env.RADAR_ENV || "unknown" });
    } catch {
      return json({ status: "error" }, 503);
    }
  }
  if (url.pathname === "/login" && request.method === "GET") {
    if (await readSession(request, env)) return redirect("/");
    return loginPage(request, env, url.searchParams.get("mode") || "login");
  }
  if (url.pathname === "/login" && request.method === "POST") return handleLogin(request, env);
  if (url.pathname === "/register" && request.method === "POST") {
    return loginPage(request, env, "login", "A criação de contas está desativada neste ambiente.", {}, 403);
  }
  if (url.pathname === "/logout") return redirect("/login", clearSessionCookie());
  const publicAsset = ["/style.css", "/visual.css", "/radar-polish.css", "/auth.js", "/icon.svg", "/manifest.webmanifest"].includes(url.pathname)
    || url.pathname.startsWith("/fonts/");
  if (publicAsset) return withSecurityHeaders(await env.ASSETS.fetch(request));

  const authenticated = await authenticate(request, env);
  if (authenticated instanceof Response) return authenticated;
  if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method) && !requestIsSameOrigin(request)) {
    return json({ erro: "Origem inválida" }, 403);
  }
  if (url.pathname.startsWith("/api/")) {
    if (request.method === "GET") return apiGet(url, env, authenticated);
    if (request.method === "POST") return apiPost(request, url, env, authenticated);
    if (request.method === "PUT") return apiPut(request, url, env, authenticated);
    if (request.method === "DELETE") return apiDelete(url, env, authenticated);
    return json({ erro: "Método não permitido" }, 405, { Allow: "GET, POST, PUT, DELETE" });
  }
  if (url.pathname === "/" || url.pathname === "/index.html") {
    const indexUrl = new URL("/index.html", request.url);
    return withSecurityHeaders(await env.ASSETS.fetch(new Request(indexUrl, request)));
  }
  return withSecurityHeaders(await env.ASSETS.fetch(request));
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    try {
      if (!env.SESSION_SECRET) return json({ erro: "SESSION_SECRET não configurado" }, 503);
      return await handleRequest(request, env);
    } catch (error) {
      if (error instanceof Response) return withSecurityHeaders(error);
      const incident = crypto.randomUUID();
      console.error("Radar Worker failure", incident, error);
      return json({ erro: "Falha interna", incidente: incident }, 500);
    }
  },

  async scheduled(_controller: ScheduledController, env: Env): Promise<void> {
    const now = new Date().toISOString();
    await env.DB.prepare(
      `INSERT INTO sync_meta(key,value) VALUES('worker_last_scheduled_at',?)
       ON CONFLICT(key) DO UPDATE SET value=excluded.value`,
    ).bind(now).run();
  },
} satisfies ExportedHandler<Env>;
