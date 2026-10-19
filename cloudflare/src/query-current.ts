export const LEAD_SCORE_SQL = `(
  CASE WHEN TRIM(COALESCE(c.email,''))<>'' THEN 20 ELSE 0 END +
  CASE WHEN TRIM(COALESCE(c.telefone,''))<>'' THEN 20 ELSE 0 END +
  CASE WHEN c.situacao='ATIVA' THEN 15 ELSE 0 END +
  CASE WHEN TRIM(COALESCE(c.nome_fantasia,''))<>'' THEN 10 ELSE 0 END +
  CASE WHEN COALESCE(c.mei,0)=0 THEN 10 ELSE 0 END +
  CASE
    WHEN julianday(date('now','-3 hours'))-julianday(c.data_abertura)<=30 THEN 25
    WHEN julianday(date('now','-3 hours'))-julianday(c.data_abertura)<=90 THEN 15
    WHEN julianday(date('now','-3 hours'))-julianday(c.data_abertura)<=365 THEN 5
    ELSE 0
  END
)`;

export const COMPANY_SOURCE_SQL = `companies c
  LEFT JOIN account_company_state acs ON acs.cnpj=c.cnpj AND acs.account_id=?`;

export const COMPANY_SELECT_SQL = `c.*,
  COALESCE(acs.lead_status,'novo') AS lead_status,
  COALESCE(acs.favorito,0) AS favorito,
  COALESCE(acs.observacoes,'') AS observacoes`;

export interface FilterSql {
  where: string;
  values: unknown[];
}

export function integerParam(value: string | null, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number.parseInt(value || "", 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, parsed));
}

export function companyFilters(params: URLSearchParams, exclude = new Set<string>(), ownerId?: string): FilterSql {
  const clauses = ["c.uf='RS'", "COALESCE(c.situacao,'')<>'TESTE'", "NOT EXISTS (SELECT 1 FROM private_companies pc WHERE pc.cnpj=c.cnpj)"];
  const values: unknown[] = [];
  const textMappings: Array<[string, string]> = [
    ["inicio", "c.data_abertura >= ?"],
    ["fim", "c.data_abertura <= ?"],
    ["municipio", "c.municipio = ?"],
    ["regiao", "c.regiao = ?"],
    ["segmento", "c.segmento = ?"],
    ["situacao", "c.situacao = ?"],
    ["porte", "c.porte = ?"],
    ["data_source", "c.data_source = ?"],
  ];
  for (const [key, clause] of textMappings) {
    const value = params.get(key)?.trim();
    if (!exclude.has(key) && value) {
      clauses.push(clause);
      values.push(value.slice(0, 180));
    }
  }
  if (!exclude.has("mei") && params.get("mei")) {
    clauses.push("c.mei = ?");
    values.push(params.get("mei") === "sim" ? 1 : 0);
  }
  if (!exclude.has("contato") && params.get("contato")) {
    clauses.push("CASE WHEN TRIM(COALESCE(c.email,''))<>'' OR TRIM(COALESCE(c.telefone,''))<>'' THEN 1 ELSE 0 END = ?");
    values.push(params.get("contato") === "sim" ? 1 : 0);
  }
  if (!exclude.has("lead_status") && params.get("lead_status")) {
    clauses.push("COALESCE(acs.lead_status,'novo') = ?");
    values.push(params.get("lead_status")!.slice(0, 40));
  }
  if (!exclude.has("favorito") && params.get("favorito")) {
    clauses.push("COALESCE(acs.favorito,0) = ?");
    values.push(params.get("favorito") === "sim" ? 1 : 0);
  }
  const cnae = (params.get("cnae") || "").replace(/\D/g, "");
  if (!exclude.has("cnae") && cnae) {
    clauses.push("substr(c.cnae,1,length(?))=?");
    values.push(cnae,cnae);
  }
  if (!exclude.has("cnae") && !cnae && params.get("cnae")?.trim()) {
    clauses.push("instr(lower(COALESCE(c.cnae_descricao,'')),lower(?))>0"); values.push(params.get("cnae")!.trim());
  }
  for (const [key, negative] of [["cnae_include", false], ["cnae_exclude", true]] as const) {
    const codes = [...new Set((params.get(key) || "").split(/[,;\s]+/).map(code => code.replace(/\D/g, "")))].filter(code => code.length >= 2 && code.length <= 7).slice(0, 40);
    if (!exclude.has(key) && codes.length) {
      // One bind per set avoids D1's 100-parameter limit with combined ICP filters.
      clauses.push(`${negative ? "NOT " : ""}EXISTS(SELECT 1 FROM json_each(?) radar_cnae WHERE substr(COALESCE(c.cnae,''),1,length(radar_cnae.value))=radar_cnae.value)`);
      values.push(JSON.stringify(codes));
    }
  }
  for (const [key, negative] of [["name_terms", false], ["name_exclude", true]] as const) {
    const terms = (params.get(key) || "").split(",").map(term => term.trim().slice(0, 80)).filter(Boolean).slice(0, 12);
    if (!exclude.has(key) && terms.length) {
      clauses.push(`${negative ? "NOT " : ""}EXISTS(SELECT 1 FROM json_each(?) radar_term WHERE instr(lower(COALESCE(c.razao_social,'')),lower(radar_term.value))>0 OR instr(lower(COALESCE(c.nome_fantasia,'')),lower(radar_term.value))>0)`);
      values.push(JSON.stringify(terms));
    }
  }
  for (const [key, column] of [["phone_available", "telefone"], ["email_available", "email"]]) {
    if (!exclude.has(key) && params.get(key)) clauses.push(`TRIM(COALESCE(c.${column},'')) ${params.get(key) === "sim" ? "<>" : "="} ''`);
  }
  const workStage = params.get("work_stage");
  if (!exclude.has("work_stage") && workStage) {
    if (!ownerId) clauses.push("0=1");
    else {
      let scope = "EXISTS (SELECT 1 FROM accessible_sales_profile_leads wl JOIN sales_profiles wp ON wp.id=wl.profile_id WHERE wp.owner_id=? AND wl.cnpj=c.cnpj";
      values.push(ownerId);
      if (!["selected", "not_selected"].includes(workStage)) { scope += " AND wl.lead_status=?"; values.push(workStage); }
      clauses.push(`${workStage === "not_selected" ? "NOT " : ""}${scope})`);
    }
  }
  const scoreMinimum = integerParam(params.get("score_min"), 0, 0, 100);
  if (!exclude.has("score_min") && scoreMinimum) {
    clauses.push(`${LEAD_SCORE_SQL} >= ?`);
    values.push(scoreMinimum);
  }
  const search = (params.get("q") || "").trim().slice(0, 180);
  if (!exclude.has("q") && search) {
    const identifier = search.replace(/[^\p{L}\p{N}]/gu, "");
    if (/\d/.test(identifier)) {
      clauses.push("(instr(lower(COALESCE(c.razao_social,'')),lower(?))>0 OR instr(lower(COALESCE(c.nome_fantasia,'')),lower(?))>0 OR instr(upper(c.cnpj),upper(?))>0)");
      values.push(search,search,identifier);
    } else {
      clauses.push("(instr(lower(COALESCE(c.razao_social,'')),lower(?))>0 OR instr(lower(COALESCE(c.nome_fantasia,'')),lower(?))>0)");
      values.push(search,search);
    }
  }
  return { where: clauses.join(" AND "), values };
}

export function normalizeCnpj(value: unknown): string {
  return String(value ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 14);
}

export function scoreCompany(company: Record<string, unknown>): number {
  let score = 0;
  if (company.email) score += 20;
  if (company.telefone) score += 20;
  if (company.situacao === "ATIVA") score += 15;
  if (company.nome_fantasia) score += 10;
  if (!company.mei) score += 10;
  const opened = Date.parse(String(company.data_abertura || ""));
  if (Number.isFinite(opened)) {
    const age = Math.floor((Date.now() - opened) / 86_400_000);
    score += age <= 30 ? 25 : age <= 90 ? 15 : age <= 365 ? 5 : 0;
  }
  return Math.min(score, 100);
}


