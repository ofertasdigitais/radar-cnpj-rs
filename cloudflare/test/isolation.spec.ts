import { env } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";
import worker, { boundedText } from "../src/worker";
import { createSessionCookie, hashPassword } from "../src/security";

const origin = "https://radar.test";
const companyCnpj = "12345678000190";
let cookieA = "";
let cookieB = "";

function sessionRequest(
  cookie: string,
  path: string,
  method = "GET",
  payload?: Record<string, unknown>,
  requestOrigin = origin,
): Promise<Response> {
  const headers = new Headers({ Cookie: cookie, Origin: requestOrigin });
  if (payload) headers.set("Content-Type", "application/json");
  return worker.fetch(new Request(`${origin}${path}`, {
    method,
    headers,
    body: payload ? JSON.stringify(payload) : undefined,
  }), env as never);
}

beforeAll(async () => {
  const password = await hashPassword("Senha-testes-2026!");
  const now = new Date().toISOString();
  await env.DB.batch([
    env.DB.prepare(
      `INSERT INTO user_accounts
       (id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at)
       VALUES(?,?,?,?,?,?,?,?,?,?)`,
    ).bind("account-a", "Conta A", "conta-a", "a@example.test", password.digest, password.salt, "vendedor", 1, now, now),
    env.DB.prepare(
      `INSERT INTO user_accounts
       (id,name,username,email,password_hash,password_salt,role,is_active,created_at,updated_at)
       VALUES(?,?,?,?,?,?,?,?,?,?)`,
    ).bind("account-b", "Conta B", "conta-b", "b@example.test", password.digest, password.salt, "vendedor", 1, now, now),
    env.DB.prepare(
      `INSERT INTO companies
       (id,cnpj,razao_social,nome_fantasia,situacao,data_abertura,cnae,segmento,municipio,regiao,uf,telefone,email,mei,cnae_descricao)
       VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    ).bind(companyCnpj, "Empresa Teste Ltda", "=EMPRESA TESTE", "ATIVA", "2026-09-20", "6201501", "Tecnologia", "Porto Alegre", "Metropolitana", "RS", "51999999999", "teste@example.test", 0, "Desenvolvimento de programas"),
  ]);
  cookieA = (await createSessionCookie(env.SESSION_SECRET, "account-a", "conta-a")).split(";", 1)[0];
  cookieB = (await createSessionCookie(env.SESSION_SECRET, "account-b", "conta-b")).split(";", 1)[0];
});

describe("isolamento multi-conta do Radar", () => {
  it("bounds actual streamed bytes without trusting Content-Length", async () => {
    for (const headers of [new Headers(), new Headers({'Content-Length':'1'})]) {
      try {
        await boundedText(new Request(origin+'/login',{method:'POST',headers,body:'x'.repeat(5000)}),4096);
        throw new Error('oversize accepted');
      } catch(error) { expect(error).toBeInstanceOf(Response); expect((error as Response).status).toBe(413); }
    }
  });

  it("shares persistent login budget across aliases; other accounts do not reset it", async () => {
    const login=async (username:string,password:string)=>worker.fetch(new Request(origin+'/login',{
      method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
      body:new URLSearchParams({username,password}).toString(),
    }),env as never);
    for(let i=0;i<8;i++)expect((await login(i%2?'CONTA-A':'a@example.test','wrong')).status).toBe(401);
    expect((await login('conta-b','Senha-testes-2026!')).status).toBe(303);
    expect((await login('conta-a','Senha-testes-2026!')).status).toBe(429);
    await env.DB.prepare('UPDATE auth_attempts SET expires_at=0').run();
    expect((await login('a@example.test','Senha-testes-2026!')).status).toBe(303);
  });
  it("exige sessão válida para consultar a API", async () => {
    const response = await worker.fetch(new Request(`${origin}/api/companies`), env as never);
    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ erro: "Autenticação necessária" });
  });

  it("isola favoritos, etapa e observações da empresa", async () => {
    const update = await sessionRequest(cookieA, `/api/leads/${companyCnpj}`, "PUT", {
      favorito: true,
      lead_status: "contatado",
      observacoes: "segredo exclusivo A",
    });
    expect(update.status).toBe(200);

    const listA = await (await sessionRequest(cookieA, `/api/companies?q=${companyCnpj}`)).json<Record<string, unknown>>();
    const listB = await (await sessionRequest(cookieB, `/api/companies?q=${companyCnpj}`)).json<Record<string, unknown>>();
    const itemA = (listA.items as Record<string, unknown>[])[0];
    const itemB = (listB.items as Record<string, unknown>[])[0];
    expect(itemA.favorito).toBe(1);
    expect(itemA.lead_status).toBe("contatado");
    expect(itemA.observacoes).toBe("segredo exclusivo A");
    expect(itemB.favorito).toBe(0);
    expect(itemB.lead_status).toBe("novo");
    expect(itemB.observacoes).toBe("");
  });

  it("rejeita leitura, alteração, exportação e exclusão de carteira de outra conta", async () => {
    const created = await sessionRequest(cookieA, "/api/team-profiles", "POST", {
      name: "Carteira A",
      role: "Vendas",
      email: "carteira-a@example.test",
    });
    expect(created.status).toBe(201);
    const profile = await created.json<{ id: string }>();

    expect((await sessionRequest(cookieA, "/api/team-leads", "POST", {
      profile_id: profile.id,
      cnpj: companyCnpj,
    })).status).toBe(201);

    expect((await sessionRequest(cookieB, `/api/team-leads?profile_id=${profile.id}`)).status).toBe(404);
    expect((await sessionRequest(cookieB, `/api/team-leads.csv?profile_id=${profile.id}`)).status).toBe(404);
    expect((await sessionRequest(cookieB, "/api/team-leads", "PUT", {
      profile_id: profile.id,
      cnpj: companyCnpj,
      observacoes: "tentativa B",
    })).status).toBe(404);

    const foreignDelete = await sessionRequest(cookieB, `/api/team-leads?profile_id=${profile.id}&cnpj=${companyCnpj}`, "DELETE");
    expect(foreignDelete.status).toBe(200);
    expect((await foreignDelete.json<{ removido: boolean }>()).removido).toBe(false);
    expect((await sessionRequest(cookieB, `/api/team-profiles/${profile.id}`, "DELETE")).status).toBe(404);

    const ownerView = await sessionRequest(cookieA, `/api/team-leads?profile_id=${profile.id}`);
    expect(ownerView.status).toBe(200);
    expect((await ownerView.json<{ total: number }>()).total).toBe(1);

    const csv = await sessionRequest(cookieA, `/api/team-leads.csv?profile_id=${profile.id}`);
    expect(csv.status).toBe(200);
    expect(await csv.text()).toContain("'=EMPRESA TESTE");
  });

  it("isola segmentações personalizadas e seus leads", async () => {
    const created = await sessionRequest(cookieA, "/api/profiles", "POST", {
      name: "Segmentação privada A",
      description: "Somente a conta A",
      filters: { municipio: "Porto Alegre" },
    });
    expect(created.status).toBe(201);
    const profile = await created.json<{ id: string }>();

    expect((await sessionRequest(cookieA, "/api/profile-leads", "POST", {
      profile_id: profile.id,
      cnpj: companyCnpj,
    })).status).toBe(201);

    expect((await sessionRequest(cookieB, `/api/profile-leads?profile_id=${profile.id}`)).status).toBe(404);
    expect((await sessionRequest(cookieB, `/api/profiles/${profile.id}`, "DELETE")).status).toBe(404);

    const profilesB = await (await sessionRequest(cookieB, "/api/profiles")).json<{ items: Record<string, unknown>[] }>();
    expect(profilesB.items.some((item) => item.id === profile.id)).toBe(false);
  });

  it("bloqueia mutações com origem diferente", async () => {
    const response = await sessionRequest(cookieA, `/api/leads/${companyCnpj}`, "PUT", {
      favorito: false,
    }, "https://malicioso.example");
    expect(response.status).toBe(403);
  });
});
