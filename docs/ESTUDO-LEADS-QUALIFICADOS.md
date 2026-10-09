# Estudo — Aprofundar o Radar CNPJ RS e gerar mais leads qualificados

*Data do estudo: 24/09/2026 · Base analisada: `data/radar.db`, competência Receita **2026-09**, sincronizada em 23/09/2026.*
*Método: leitura do código (`app.py`, `syncer.py`, `serpro.py`, `importer.py`, `static/`), consultas SQLite somente leitura (`mode=ro`), leitura do catálogo público da Receita e pesquisa web. Nenhum arquivo de código, banco ou configuração foi alterado.*

---

## Sumário executivo

A base tem volume (133 mil estabelecimentos do RS) e quase 100% de "contato preenchido", mas esse número engana. Três problemas de dados fazem o score atual marcar lead demais como prioritário:

1. **89,5% dos telefones são celulares sem o 9º dígito.** A Receita grava 8 dígitos. Hoje nenhum desses números abre direto no WhatsApp nem pode ser discado como está.
2. **O score atual quase não diferencia um lead do outro.** Contato vale 40 pontos e 99,8% da base já tem contato. Resultado: 27,3% da base (36.365 empresas) aparece como "alto potencial". Desses, 5.166 usam telefone ou e-mail de contador ou plataforma de abertura, compartilhado com 5 ou mais empresas.
3. **A base acumula registros vencidos.** São 33.404 registros com mais de 120 dias, fora da janela que o sincronizador atualiza. A situação cadastral deles está congelada: uma empresa baixada depois continua aparecendo como ATIVA.

Com uma definição mais rigorosa de lead qualificado (ativa, contato próprio, CNAE de valor, até 90 dias), sobram **47.426 leads**. Desses, **13.002 não são MEI** e só **2.321 têm e-mail de domínio próprio**. Esse funil mostra onde está o ganho: primeiro qualidade e priorização, depois volume.

As cinco recomendações de maior impacto estão na seção 7.

---

## 1. Como o sistema funciona hoje

### 1.1 Fontes de dados

| Fonte | Arquivo | Situação atual |
|---|---|---|
| **Dados abertos CNPJ (Receita)** via WebDAV | `syncer.py` | **Ativa.** O catálogo é verificado a cada hora e baixa uma competência mensal nova (≈7,1 GB: Estabelecimentos 5,38 GB + Empresas 1,38 GB + Simples 0,31 GB). Filtra `UF=RS` e `data_inicio >= hoje-120 dias`. Usa Municipios e Cnaes. **Não baixa** Socios (0,69 GB), Naturezas, Qualificacoes nem Motivos. |
| **Serpro Consulta CNPJ** | `serpro.py` | **Implementada, não configurada.** 0 execuções em `monitor_runs`, 0 candidatos e 0 registros com `serpro_checked_at`. Só revalida CNPJs que já estão na base; não descobre CNPJs novos. |
| **`RADAR_DISCOVERY_URL`** | `serpro.py::_discover` | Não configurada. Aceita um feed JSON de CNPJs para o Serpro validar. |
| **CSV manual** | `importer.py` | Disponível. Normaliza aliases de colunas, calcula segmento e região. Todos os 133.042 registros atuais vieram da Receita (`data_source`). |

### 1.2 Campos armazenados (`companies`)

cnpj, razão social, nome fantasia, situação, data de abertura, CNAE principal, descrição e CNAEs secundários, segmento (seção CNAE), município, região, UF, CEP, bairro, logradouro, número, **um** telefone, e-mail, porte, MEI (S/N), mais os campos comerciais legados (`lead_status`, `favorito`, `observacoes`) e `serpro_checked_at`/`data_source`.

**Campos que já chegam nos arquivos baixados e são descartados pelo `syncer.py`:**

| Arquivo (índice) | Campo descartado | Uso comercial |
|---|---|---|
| Estabelecimentos [3] | Matriz/filial | Deduplicar grupos e priorizar a matriz |
| Estabelecimentos [6], [7] | Data e motivo da situação cadastral | Detectar empresa que "nasceu e morreu" |
| Estabelecimentos [16] | Complemento | Visita e validação de endereço (sala comercial ou residência) |
| Estabelecimentos [23]–[26] | **Telefone 2** e fax | Segundo canal de contato |
| Estabelecimentos [28], [29] | Situação especial | Recuperação judicial e outros alertas |
| Empresas [2] | **Natureza jurídica** | Separa LTDA, SLU, S/A, EI, associações e órgãos públicos |
| Empresas [3] | Qualificação do responsável | — |
| Empresas [4] | **Capital social** | Melhor indicador aberto de porte ou investimento inicial |
| Simples [1]–[3] | Opção, data e exclusão do Simples | Regime tributário (útil para quem vende contabilidade ou software) |
| Simples [5], [6] | Data de opção e exclusão do MEI | Hoje o código usa só a flag S/N. A data de exclusão mostra MEI desenquadrado, um bom sinal de crescimento |
| Socios (não baixado) | Nº de sócios, sócio PJ, faixa etária, data de entrada | Sinal de estrutura, grupo econômico e decisor |

Fonte do layout: [Metadados dos Dados Abertos do CNPJ — Receita Federal](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf).

### 1.3 Score de potencial (`LEAD_SCORE_SQL` e `score_company`, `app.py`)

| Critério | Pontos |
|---|---|
| E-mail preenchido | 20 |
| Telefone preenchido | 20 |
| Situação ATIVA | 15 |
| Nome fantasia preenchido | 10 |
| Não é MEI | 10 |
| Aberta há ≤30 / ≤90 / ≤365 dias | 25 / 15 / 5 |

Um score **≥ 80** vira "Alto potencial" (perfil de sistema `alto`, painel de oportunidades). O próprio código documenta que ele mede *completude e acionabilidade*, não intenção de compra.

Problemas medidos na base:
- **Contato não discrimina:** 99,8% das empresas têm telefone e e-mail, então 40 pontos são praticamente constantes.
- **Nome fantasia e "não MEI" medem a mesma coisa:** dos 13.562 registros com nome fantasia, 13.558 não são MEI (MEI com fantasia: 4). O MEI perde 20 pontos pelo mesmo motivo.
- **Distribuição concentrada:** os scores ficam em 60, 70 e 80 (40.086 / 46.850 / 27.123 registros). O limiar 80 captura 36.365 empresas (27,3%).
- **Não considera:** CNAE ou aderência ao cliente ideal, contato compartilhado, capital, natureza jurídica, região, desfechos reais do funil.

### 1.4 Perfis, carteiras, funil, segmentações e monitor

- **Segmentações salvas** (`prospecting_profiles` + `profile_leads`): filtros persistidos. Existem 5 de sistema (geral, MEI, com contato, alto, favoritos) e 0 criadas pelo usuário; nenhum lead em `profile_leads`.
- **Perfis individuais / carteiras** (`sales_profiles` + `sales_profile_leads`): 2 perfis e 2 leads, com etapa, favorito, observações e estratégia. As etapas são `novo → qualificado → contatado → negociacao → convertido / descartado`.
- **Funil legado** em `companies.lead_status` (1 contatado, 1 descartado). Existe também uma tabela `account_company_state` (0 linhas) que o `app.py` atual não referencia. **São três lugares para o estado comercial.** Isso precisa ser consolidado antes de medir conversão.
- **Não há histórico:** o sistema grava só a etapa atual e `updated_at`. Não registra quem contatou, por qual canal, quando, com que resultado nem por que descartou. Sem isso o score não aprende.
- **Exportação:** CSV da lista (frontend) e CSV da carteira (`/api/team-leads.csv`). Não há link de WhatsApp, `tel:` nem integração com CRM.
- **Monitor diário Serpro:** pronto, mas sem credenciais.

---

## 2. Qualidade da base hoje (números medidos)

Total: **133.042 estabelecimentos** do RS, **132.318 CNPJs básicos**, 497 municípios, 907 CNAEs distintos. Datas de abertura de 20/04/2026 a 13/09/2026.

### 2.1 Preenchimento e situação

| Indicador | Valor |
|---|---|
| Com telefone | 132.755 (99,8%) |
| Com e-mail | 132.736 (99,8%) |
| MEI | 90.447 (68,0%) |
| Com nome fantasia | 13.562 (10,2%) |
| Com CNAE secundário | 71.699 (53,9%); média de 3,4 por empresa |
| CEP, porte e descrição CNAE vazios | 0% |
| Número vazio ou S/N | 2.944 (2,2%) |
| Validados via Serpro | 0 |
| Região "Demais regiões" (sem mapeamento) | **62.184 (46,7%)**. `region_for` mapeia só 22 cidades |

| Situação | Qtde |
|---|---|
| ATIVA | 123.544 (92,9%) |
| BAIXADA | 8.662 (6,5%) |
| SUSPENSA | 828 |
| NULA / INAPTA | 6 / 2 |

A base inclui empresas baixadas poucas semanas depois de abrir: 995 em abril, 2.347 em maio, 2.256 em junho, 1.696 em julho, 1.184 em agosto. Elas não deveriam aparecer como lead.

| Porte × MEI | Qtde |
|---|---|
| ME + MEI | 90.447 |
| ME não MEI | 31.582 |
| DEMAIS | 6.267 |
| EPP | 4.746 |

### 2.2 Idade (data de abertura em relação a 24/09/2026)

| Faixa | Qtde |
|---|---|
| ≤ 30 dias | 15.439 |
| 31–90 dias | 55.773 |
| 91–120 dias | 27.215 |
| **> 120 dias** (fora da janela do sync) | **33.404**, sem atualização de situação |

Por mês: abr 10.620 · mai 26.459 · jun 27.736 · jul 29.309 · ago 28.789 · set (parcial até dia 13) 10.129. Em média, **≈26 mil empresas ativas novas por mês** no RS.

**Defasagem:** a competência 2026-09 traz aberturas até 13/09 e o sync rodou em 23/09. O lead mais novo chega com cerca de 10 dias de atraso e pode chegar a 40 dias antes da próxima competência.

### 2.3 Qualidade real do contato

| Indicador | Valor |
|---|---|
| Telefones com 10 dígitos (DDD + 8) | 131.234 (98,6%) |
| Destes, começam com 6–9 (**celular sem o 9º dígito**) | **119.090 (89,5% da base)** |
| Fixos (começam com 2–5) | 12.144 |
| Telefones "lixo" (2–4 dígitos, só DDD) | ≈1.480 |
| DDD fora do RS (contador de outro estado?) | 8.394 |
| Telefone exclusivo de 1 empresa | 119.995 (90,2%) |
| Telefones repetidos em ≥5 empresas | 6.729 registros. O mais repetido aparece em 1.152 empresas |
| E-mail exclusivo de 1 empresa | 116.489 (87,6%) |
| E-mails repetidos em ≥5 empresas | 8.954 registros |
| E-mails de plataformas de abertura MEI/contabilidade online (maismei, contabilizei) | 3.319 |
| **E-mail em webmail gratuito** (gmail, hotmail, outlook, yahoo…) | **118.631 (89,4%)** |
| E-mail de domínio próprio e exclusivo | **6.125 (4,6%)** |
| Domínio com erro de digitação (gmai.com, gamil.com, gmail.con…) | 470 |
| E-mail com sintaxe inválida | 38 |

**Leitura:** "tem contato" não significa "tem contato do decisor". Para MEI, telefone e e-mail geralmente são pessoais do titular. Isso é dado pessoal e tem implicações de LGPD (seção 5). Para parte das LTDA, o contato é do escritório de contabilidade.

### 2.4 Duplicidades

- CNPJ básico com mais de 1 estabelecimento: 1.096 registros. Filiais (ordem ≠ 0001): 2.969 (2,2%).
- Razão social repetida: 1.306 registros.
- Grupos por contato compartilhado: veja 2.3. É a maior fonte de "duplicidade comercial", porque vários CNPJs levam à mesma pessoa, normalmente o contador.

### 2.5 CNAEs e municípios

**Segmentos** (total / MEI): Comércio 23.184 / 15.545 · Transporte 19.730 / 15.927 · Serviços profissionais 12.896 / 6.574 · Construção 11.944 / 9.574 · Serviços administrativos 11.481 / 7.630 · Indústria 10.911 / 9.049 · Outros serviços 10.353 · Alimentação 8.842 · Educação 5.887 · Saúde 5.336 · Tecnologia 4.334.

**Top CNAEs:** 7319-0/02 Promoção de vendas (7.307) · 5320-2/01 Malote (5.580) · 8219-9/99 Apoio administrativo n.e. (5.412) · 4399-1/03 Alvenaria (4.985) · 9602-5/01 Cabeleireiros (3.982) · 4781-4/00 Vestuário (3.926) · 4930-2/01 e 4930-2/02 Transporte de carga (3.596 e 3.142) · 4923-0/02 Motorista com carro (3.047) · 5620-1/04 Comida para domicílio (2.722).

Sete CNAEs típicos de "PJ de trabalhador autônomo" (promoção de vendas, malote, entregas, apoio administrativo n.e., motorista, cuidador domiciliar, serviço doméstico) somam **27.925 registros (21,0%)**. Para a maioria dos produtos B2B têm baixo valor e deveriam ser excluídos ou rebaixados conforme o cliente ideal.

**Top municípios:** Porto Alegre 23.221 · Caxias do Sul 7.322 · Canoas 5.288 · Pelotas 4.189 · Gravataí 3.941 · Novo Hamburgo 3.640 · Passo Fundo 3.571 · Santa Maria 3.305 · São Leopoldo 3.096 · Viamão 2.795.

### 2.6 Dados pessoais embutidos

A razão social de MEI segue o padrão `NN.NNN.NNN NOME COMPLETO DA PESSOA`: o CNPJ básico seguido do nome civil do titular. O CPF **não** aparece (0 ocorrências de 11 dígitos em 90.447 MEIs). Mesmo assim, nome completo + telefone + e-mail pessoal identificam uma pessoa física.

---

## 3. Definição proposta de "lead qualificado"

> **Lead qualificado** é um estabelecimento do RS que atende a todos os critérios abaixo:
> 1. **Novo:** início de atividade há até 90 dias (janela ajustável por perfil).
> 2. **Vivo:** situação ATIVA na competência mais recente, sem situação especial e sem exclusão do Simples/MEI por pendência.
> 3. **Acionável:** pelo menos um canal válido e próprio, isto é, telefone normalizado (celular com 9º dígito) ou e-mail sintaticamente válido, não compartilhado com 3 ou mais outras empresas e fora da lista de oposição (opt-out).
> 4. **Aderente ao cliente ideal (ICP) do perfil:** CNAE principal *ou secundário* na lista-alvo, fora da lista de exclusão; porte, natureza jurídica e faixa de capital dentro do alvo; município ou região na área atendida.
> 5. **Com sinal de atividade real** (pelo menos um, para prioridade máxima): nome fantasia; e-mail de domínio próprio com domínio ativo; ficha no Google (place_id encontrado); telefone fixo comercial; mais de 1 sócio ou sócio PJ; capital acima do limiar do perfil.
>
> Os critérios 1 a 4 são o **filtro** (é ou não é lead). O critério 5 e o histórico de conversão entram no **score** (ordem de ataque).

### Funil medido com a base atual

| Filtro cumulativo | Registros |
|---|---|
| Base total | 133.042 |
| ATIVA | 123.544 |
| + contato próprio (telefone e e-mail compartilhados por no máximo 2 empresas) | 109.656 |
| + fora dos 7 CNAEs de baixo valor | 86.433 |
| + até 90 dias | **47.426** (34.424 MEI) |
| + não MEI | **13.002** |
| + e-mail de domínio próprio | **2.321** |

### Lacunas em relação à definição

| Critério | Lacuna atual |
|---|---|
| Novo | 33.404 registros fora da janela, sem atualização; defasagem de 10 a 40 dias |
| Vivo | Sem data e motivo da situação nem situação especial; baixadas aparecem na lista |
| Acionável | Celulares sem 9º dígito; sem flag de contato compartilhado; sem validação de e-mail; sem opt-out |
| ICP | Filtro de CNAE só por prefixo do principal; ignora secundários; não há lista de exclusão; sem capital nem natureza jurídica; 46,7% sem região |
| Atividade real | Nenhum sinal externo (site, Google, sócios) |
| Aprendizado | Sem registro de interações e desfechos |

---

## 4. Fontes para enriquecer e encontrar leads

Preços consultados em set/2026. "Fonte secundária" indica valor citado por terceiros, que deve ser confirmado com o fornecedor antes de contratar.

### 4.1 Campos ainda não usados dos dados abertos da Receita (grátis)

| Item | Ganho | Custo | Esforço | Risco | Backend/banco |
|---|---|---|---|---|---|
| Natureza jurídica, capital social, qualificação (Empresas.zip, já baixado) | Alto: separa LTDA capitalizada de EI/MEI e exclui órgãos públicos e associações | Grátis | P | Nenhum | Sim: 3 colunas + ajuste no sync |
| Telefone 2, matriz/filial, complemento, data e motivo da situação, situação especial (Estabelecimentos.zip, já baixado) | Alto: 2º canal, exclusão de mortas, dedup | Grátis | P | Nenhum | Sim |
| Datas de opção e exclusão do Simples e do MEI (Simples.zip, já baixado) | Médio: regime tributário; MEI desenquadrado é sinal de crescimento | Grátis | P | Nenhum | Sim |
| Socios.zip (+0,69 GB por mês) | Médio: nº de sócios, sócio PJ (grupo), faixa etária, nome do decisor | Grátis | M | **LGPD:** nome de sócio PF é dado pessoal e o CPF vem mascarado. Guardar só o necessário (nº de sócios, existência de sócio PJ, nome e qualificação do administrador para personalizar a abordagem) | Sim: tabela nova |
| Naturezas / Qualificacoes / Motivos (KB) | Descrições legíveis | Grátis | P | Nenhum | Sim |

Fonte: [Metadados CNPJ — Receita](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf) · [Dados Abertos CNPJ — dados.gov.br](https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj). Tamanhos medidos no catálogo WebDAV da competência 2026-09.

### 4.2 APIs de consulta de CNPJ

Observação importante: **BrasilAPI, ReceitaWS, CNPJá (aberta), OpenCNPJ, minhaReceita e CNPJ.ws derivam da mesma base aberta mensal** que o Radar já processa inteiro. Para enriquecimento em lote, elas acrescentam pouco e têm limites baixos. A única fonte oficial com dado do dia é o Serpro.

| Fonte | Limites / preço | Uso comercial | Veredito |
|---|---|---|---|
| **Serpro Consulta CNPJ** (oficial; Básica, QSA, Empresa) | Cobrança por consulta em faixas progressivas; tabela na [Loja Serpro](https://loja.serpro.gov.br/consultacnpj) (página bloqueia robôs, **valor a confirmar**). Exige e-CNPJ | Sim, contratual | Útil **só** para revalidar os leads priorizados no mesmo dia. Não descobre CNPJs novos. O código já existe; ligar com `RADAR_SERPRO_DAILY_LIMIT` baixo |
| **CNPJá** | API aberta: 5 req/min por IP; conta grátis com créditos limitados; planos pagos por créditos ([preços](https://cnpja.com/en/pricing), página devolveu 429 na consulta) | Sim | Opção paga para Simples e Inscrição Estadual pontuais; dispensável se o dump for bem usado |
| **ReceitaWS** | Pública: 3 req/min; planos pagos a partir de R$ 149/mês (fonte secundária: [Hub do Desenvolvedor](https://blog.hubdodesenvolvedor.com.br/api-de-consulta-de-cnpj/), [ReceitaWS](https://receitaws.com.br/)) | Sim | Dispensável |
| **BrasilAPI / OpenCNPJ** | Gratuitas, "uso razoável" ([OpenCNPJ](https://opencnpj.org/)) | Sim | Dispensáveis para lote. No máximo, fallback de consulta unitária na ficha |

### 4.3 Google Places API (New): sinal de "empresa real" e contato comercial

- **Campos úteis:** `nationalPhoneNumber`, `websiteUri`, `rating`, `userRatingCount`, `regularOpeningHours` pertencem ao **SKU Enterprise**; `businessStatus` e `displayName`, ao Pro ([Data fields](https://developers.google.com/maps/documentation/places/web-service/data-fields)).
- **Preço oficial** (página atualizada em 17/09/2026): Text Search Pro US$ 32/mil (5.000 grátis/mês); **Text Search Enterprise US$ 35/mil (1.000 grátis/mês)**; Enterprise + Atmosphere US$ 40/mil ([Pricing](https://developers.google.com/maps/billing-and-pricing/pricing)). Place Details Enterprise sai por cerca de US$ 20/mil com 1.000 grátis/mês ([Woosmap, jun/2026](https://www.woosmap.com/blog/google-places-api-pricing), fonte secundária).
- **Termos:** *"You must not pre-fetch, cache, or store Places API content"*, exceto o **place_id**, que pode ser guardado indefinidamente. Exibir dados sem mapa exige o logo e a atribuição do Google ([Policies](https://developers.google.com/maps/documentation/places/web-service/policies)).
- **Desenho compatível com os termos:** (a) procurar "nome fantasia/razão + município" só para leads que já passaram no filtro de qualificação e **guardar apenas `place_id` e se foi encontrado**. Ter place_id já é um sinal de atividade real. (b) Buscar telefone, site, avaliações e horário **no momento em que o vendedor abre a ficha**, exibir com atribuição e não gravar.
- **Custo estimado:** até 1.000 leads/mês verificados cabem no gratuito. 3.000/mês ≈ 2.000 × US$ 0,035 ≈ **US$ 70/mês**.
- **Limitação:** MEI recém-aberto raramente tem ficha no Google. A taxa de acerto deve ser maior em LTDA com nome fantasia (13,5 mil registros). Vale medir com uma amostra de 200 antes de escalar.
- **Esforço:** M · **Risco:** termos de uso (cache) e custo descontrolado. Exige orçamento e alerta de cobrança no Google Cloud · **Backend:** sim (coluna `place_id`, endpoint proxy com chave no servidor).

### 4.4 Presença digital: site e domínio

- **E-mails de domínio próprio:** 6.125 exclusivos. O domínio do e-mail é um candidato natural a site.
- **Registro.br RDAP** (gratuito, oficial): cerca de 30 consultas a cada 5 min para domínios ([rdap.registro.br](https://registro.br/rdap/); limites citados em [Homehost](https://www.homehost.com.br/blog/dominio/whois-rdap-protocolo-de-dominios/)). Retorna data de criação e status do `.br`. **Domínio criado junto com o CNPJ é sinal forte de investimento.**
- **Checagem de MX e site:** DNS-over-HTTPS público (grátis) para MX e um `HEAD https://dominio` para saber se o site responde. É só `urllib`, sem dependências novas.
- Custo grátis · Esforço P–M · Risco baixo (respeitar o rate limit) · Backend sim.
- **Redes sociais:** apenas links informados pela própria empresa, por exemplo no site. **Não** fazer scraping de Instagram, Facebook ou LinkedIn: os termos proíbem coleta automatizada.

### 4.5 Contexto público

| Fonte | Uso | Custo | Esforço |
|---|---|---|---|
| **IBGE — API de localidades** ([docs](https://servicodados.ibge.gov.br/api/docs/)) | Mapear os 497 municípios em regiões oficiais (intermediárias/imediatas) ou COREDEs e **zerar os 46,7% "Demais regiões"** | Grátis | P |
| **IBGE — Agregados/SIDRA** ([API](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3), [SIDRA](https://sidra.ibge.gov.br/)) | PIB municipal, população, CEMPRE: ponderar a prioridade por potencial econômico do município e calcular "aberturas por mil habitantes" | Grátis | P–M |
| **PNCP — API de consulta** ([Manual de consultas](https://gist.github.com/Micael106/04a3e5515057ab11ea8797603682f0bd), `pncp.gov.br/api/consulta/v1`) | Marcar fornecedores do governo (sinal B2G). Para empresas com menos de 90 dias o acerto será baixo | Grátis | M |
| **JucisRS** | Atos societários (alterações, aumento de capital). Não há API pública aberta conhecida; certidões são pagas | — | G, baixa prioridade |

### 4.6 Fontes pagas (só para comparação)

| Fornecedor | Preço | Observação |
|---|---|---|
| **Casa dos Dados** | R$ 0,01 por CNPJ exportado; 10 mil ≈ R$ 100 (verificado jul/2026 por [LeadJet](https://leadjet.com.br/casa-dos-dados/); [preços oficiais](https://portal.casadosdados.com.br/precos)) | Mesma base aberta, com filtros prontos e API. Não resolve contato do decisor |
| **Econodata** | R$ 590–890/mês (fonte secundária: [LeadJet](https://leadjet.com.br/alternativa-econodata/); [planos](https://prospecte.econodata.com.br/prospectar-planos-precos)) | Promete "contatos validados" e integração com CRM |
| Serpro | Por consulta (a confirmar) | Único oficial com dado do dia |

**Conclusão:** para o recorte "empresa nova do RS", o Radar já tem a mesma matéria-prima dessas ferramentas. O diferencial pago é contato validado e dado do dia. Vale considerar só depois que o funil registrar resultados e mostrar que o contato atual é o gargalo.

---

## 5. LGPD: tratamento explícito

**O que é dado pessoal aqui.** Dados da pessoa jurídica (CNPJ, CNAE, capital, endereço comercial) não são dados pessoais. Já para **MEI e EI** (68% da base), a razão social traz o **nome completo do titular**, e telefone e e-mail são quase sempre pessoais (89% em webmail). Nome de sócio e nome de administrador também são dados pessoais. O CPF de sócio vem mascarado no dump ([Metadados](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf), nota 2).

**Base legal: legítimo interesse** (LGPD, art. 7º, IX, e art. 10). Veja o [Guia Orientativo da ANPD sobre Legítimo Interesse (fev/2024)](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia_orientativo_hipoteses_legais_tratamento_de_dados_pessoais_legitimo_interesse). O art. 7º, §§3º, 4º e 7º exige, para dados de acesso público, respeitar a finalidade, a boa-fé e o interesse público que justificaram a publicação.

Medidas recomendadas:

1. **Teste de balanceamento (LIA) documentado:** finalidade (oferta B2B pertinente à atividade da empresa), necessidade (só os campos usados), expectativa do titular (quem abre CNPJ espera contato comercial pertinente, não massivo) e salvaguardas.
2. **Minimização:** não importar CPF (mascarado) nem faixa etária de sócio sem necessidade; não exportar a razão social de MEI em massa quando o nome fantasia bastar; limitar a retenção (por exemplo, remover leads não trabalhados após 12 meses).
3. **Transparência:** no primeiro contato, informar a fonte ("dados públicos do CNPJ na Receita Federal") e como pedir para não ser mais contatado. Publicar um aviso de privacidade simples.
4. **Direito de oposição e opt-out** (art. 18, §2º, e art. 18 em geral): criar uma **lista de supressão** persistente por CNPJ, telefone e e-mail, respeitada pela busca, pela exportação e pelo WhatsApp e **preservada nas re-sincronizações**. Registrar data e canal do pedido. Atender em prazo curto (a LGPD fala em "imediato" ou até 15 dias para confirmação de existência e acesso, art. 19).
5. **Canais:** e-mail e WhatsApp em massa sem consentimento são o maior risco, tanto regulatório quanto de bloqueio pela plataforma. A política do WhatsApp Business exige opt-in para mensagens iniciadas pela empresa via API. Por isso: **click-to-chat manual (`wa.me`) um a um é aceitável; disparo via API para lista fria não é.**
6. **Segurança e registro:** o Radar já tem login e senhas com hash. Faltam logs de exportação (quem exportou o quê, e quando) e perfil de acesso para exportar.
7. **Não fazer:** comprar listas de dados pessoais; fazer scraping de redes sociais; enriquecer MEI com dados de pessoa física (CPF, endereço residencial, renda).

Referências de mercado sobre prospecção B2B e LGPD: [Speedio](https://speedio.com.br/blog/lgpd-na-prospeccao-b2b-como-usar-dados-de-contato-dentro-da-lei-sem-travar-as-vendas/), [Neoway](https://blog.neoway.com.br/lgpd-na-prospeccao/). *Isto não é parecer jurídico. Valide o LIA com um advogado.*

---

## 6. Melhorias propostas no próprio sistema

Legenda: **Esforço** P (≤2 dias) / M (≤2 semanas) / G (>2 semanas). **BD** indica se exige mudança de backend ou banco.

| # | Proposta | Ganho esperado | Custo | Esforço | Risco | BD |
|---|---|---|---|---|---|---|
| 1 | **Normalizar telefone** para E.164 e inserir o 9º dígito em celulares (primeiro dígito 6–9), guardando o original; botões `tel:` e **WhatsApp click-to-chat** (`wa.me/55…`) com mensagem-modelo | 119 mil números passam a ser acionáveis com 1 clique | Grátis | P | Baixo. Alguns números antigos ou de rádio podem não existir; o original fica guardado | Sim (coluna ou função de normalização + frontend) |
| 2 | **Flag de contato compartilhado:** contar ocorrências por telefone e e-mail; marcar "contato de contador/plataforma" quando houver 3 ou mais empresas ou domínio conhecido (maismei, contabilizei…) | Tira ~5,2 mil falsos "alto potencial"; permite trabalhar o **contador como canal** (1 contato → dezenas de empresas) | Grátis | P | Nenhum | Sim |
| 3 | **Corrigir a janela e a obsolescência:** marcar ou excluir registros fora da janela; ou ampliar o recorte para 365 dias (mais linhas, mas situação sempre atual); excluir BAIXADA/NULA/INAPTA dos leads | Elimina 33 mil registros com situação congelada e 8,7 mil baixadas | Grátis | P | Baixo. Preservar os leads que estão em carteira | Sim (sync) |
| 4 | **Extrair campos já baixados** (seção 4.1: natureza, capital, telefone 2, matriz/filial, data e motivo da situação, situação especial, Simples/MEI com datas) | Base para ICP e score | Grátis | P–M | Baixo (layout estável; testar) | Sim |
| 5 | **Região oficial IBGE** para os 497 municípios | 62 mil registros deixam de ser "Demais regiões" | Grátis | P | Nenhum | Sim (tabela ou constante) |
| 6 | **ICP por segmentação:** listas de CNAE incluídos e excluídos, com opção de considerar **secundários**; porte, natureza e faixa de capital; municípios | Leads alinhados ao que cada vendedor vende; exclui os 21% de baixo valor | Grátis | M | Nenhum | Sim (`filters_json` já existe; faltam os filtros no SQL) |
| 7 | **Score v2** em três eixos: *Aderência* (ICP), *Acionabilidade* (contato próprio e válido) e *Sinais de atividade*; pesos configuráveis; exibir o motivo de cada ponto | Priorização real; o limiar 80 volta a significar algo (meta: ≤10% da base) | Grátis | M | Baixo | Sim |
| 8 | **Validação de e-mail:** sintaxe, correção de typos comuns (470 casos), MX via DNS-over-HTTPS, marcação webmail vs. domínio próprio | Menos bounce; identifica 6,1 mil com domínio próprio | Grátis | P | Baixo | Sim |
| 9 | **Presença digital:** para domínio próprio, consultar RDAP (data de criação) e verificar se o site responde | Sinal forte de atividade | Grátis | M | Rate limit do RDAP (fila lenta) | Sim |
| 10 | **Google Places sob demanda** (seção 4.3): guardar só `place_id`; detalhes ao abrir a ficha | Sinal de atividade + telefone comercial e horário | ≤US$ 70/mês para 3 mil leads | M | Termos (cache) e custo; exige chave no servidor | Sim |
| 11 | **Consolidar o estado comercial** (`companies.lead_status` × `sales_profile_leads` × `account_company_state`) em um único modelo | Pré-requisito para medir conversão | Grátis | M | Migração de dados (há só 4 registros hoje, risco baixo **agora**) | Sim |
| 12 | **Registro de interações** (`lead_events`: data, perfil, canal, resultado, motivo de descarte padronizado) | Métrica de conversão por CNAE, região, porte e canal; base para o score aprender | Grátis | M | Nenhum | Sim |
| 13 | **Score que aprende:** com ~200+ desfechos, calibrar pesos por regressão logística simples (offline, script Python sem dependências ou planilha), mostrando a taxa de conversão real por faixa | Score baseado em resultado, não em opinião | Grátis | M–G | Viés de amostra pequena; revisar a cada trimestre | Sim |
| 14 | **Alertas de novos leads do ICP:** após cada sync ou rodada Serpro, badge "N novos no seu perfil" e resumo diário ou semanal por e-mail | Ataque nos primeiros dias, quando a empresa está contratando fornecedores | Grátis (SMTP próprio) | M | Baixo | Sim |
| 15 | **Deduplicação e agrupamento:** agrupar por CNPJ básico (matriz e filiais) e por contato compartilhado; mostrar "mesmo grupo" na ficha | Evita dois vendedores no mesmo decisor | Grátis | P–M | Nenhum | Sim |
| 16 | **Lista de supressão (opt-out) + aviso de fonte + log de exportação** | Conformidade LGPD | Grátis | P | Nenhum; **reduz** risco | Sim |
| 17 | **Exportação para CRM:** CSV no layout de importação de RD Station, Pipedrive e HubSpot; depois, webhook | Menos retrabalho | Grátis | P (CSV) / M (API) | Baixo | Sim |
| 18 | **Serpro para revalidação** dos top-N do dia (código pronto) | Situação e contato confirmados no dia do contato | Por consulta (a confirmar) | P (configuração) | Custo; e-CNPJ | Não (só configuração) |
| 19 | **Feed diário de novos CNPJs** (`RADAR_DISCOVERY_URL`) de um fornecedor comercial | Elimina a defasagem de 10–40 dias | Pago, sob cotação | M | Dependência de fornecedor; LGPD do fornecedor | Não (já suportado) |
| 20 | Contexto IBGE (PIB, população) e PNCP | Ajuste fino de prioridade | Grátis | M | Nenhum | Sim |

### Esboço do Score v2 (ponto de partida, a calibrar com resultados)

| Eixo | Variável | Pontos |
|---|---|---|
| **Filtros eliminatórios** | Não ATIVA, situação especial, opt-out, CNAE excluído, fora da área | Fora da lista |
| **Aderência (40)** | CNAE principal no alvo 20 / só secundário 10 · porte ou natureza no alvo 10 · capital ≥ limiar do perfil 10 |
| **Acionabilidade (30)** | Celular válido e exclusivo 15 (compartilhado 3–4: 5; ≥5: 0) · e-mail válido e exclusivo 10 (domínio próprio +5) |
| **Atividade real (20)** | Nome fantasia 4 · domínio ativo/site 6 · place_id Google 6 · >1 sócio ou sócio PJ 4 |
| **Recência (10)** | ≤15 dias 10 · ≤30 7 · ≤60 4 · ≤90 2 |

MEI deixa de ser penalizado por si só. Se o produto não serve para MEI, isso entra como filtro do ICP e não como desconto no score.

---

## 7. As 5 recomendações de maior impacto

1. **Corrigir o telefone e ligar o WhatsApp click-to-chat** (itens 1 e 16). 89,5% da base está com o número "quebrado" para o canal que o vendedor mais usa. O custo é quase zero e o efeito é imediato.
2. **Refazer o score (v2) com ICP por segmentação e flag de contato compartilhado** (itens 2, 6 e 7). Hoje 27% da base é "prioritária" e ~5 mil desses leads são contador ou plataforma. O objetivo é uma lista curta e aderente por vendedor, excluindo os 21% de CNAEs de baixo valor.
3. **Aproveitar o dump que já é baixado e limpar a base vencida** (itens 3, 4 e 5): capital, natureza jurídica, telefone 2, situação, datas do Simples/MEI e regiões IBGE; tirar os 33 mil registros congelados e as 8,7 mil baixadas.
4. **Medir resultados:** consolidar o funil e registrar interações e motivos de descarte (itens 11, 12 e 13). Sem isso nenhuma fonte paga se justifica e o score não aprende.
5. **Sinais de atividade real a custo baixo, com LGPD em ordem** (itens 8, 9, 10 e 16): domínio próprio via RDAP e MX, Google Places só para leads já filtrados (guardando apenas o place_id) e lista de oposição com aviso de fonte.

---

## 8. Plano em fases

### Fase 1: ganhos rápidos (1–2 semanas)
**Objetivo: a lista atual ficar confiável e acionável.**
1. Consolidar o estado comercial (item 11). Existem só 4 registros hoje, então a migração é trivial **agora** e fica cara depois.
2. Normalizar telefone + botões `tel:`/WhatsApp (item 1).
3. Excluir não-ATIVAS e tratar os registros fora da janela (item 3).
4. Extrair os campos adicionais de Empresas, Estabelecimentos e Simples, sem nenhum download novo (item 4).
5. Regiões IBGE (item 5).
6. Flag de contato compartilhado + validação de e-mail (itens 2 e 8).
7. Lista de supressão, aviso de fonte e log de exportação (item 16).

*Por que primeiro:* é grátis, não depende de terceiros e todas as etapas seguintes (score, alertas, enriquecimento pago) dependem de dados limpos e de um modelo comercial único.

### Fase 2: médio prazo (3–8 semanas)
**Objetivo: priorização por cliente ideal e início da medição.**
1. ICP por segmentação (CNAE incluído/excluído com secundários, porte, natureza, capital, área) (item 6).
2. Score v2 com explicação dos pontos (item 7).
3. Registro de interações e motivos de descarte (item 12).
4. Alertas de novos leads do perfil (item 14).
5. Dedup e agrupamento (item 15), exportação CSV para CRM (item 17).
6. Socios.zip mínimo (nº de sócios, sócio PJ, nome e qualificação do administrador) com LIA documentado.
7. Piloto de presença digital: RDAP/MX para domínio próprio (item 9) e **amostra de 200 leads no Google Places** para medir a taxa de acerto antes de ativar (item 10).

*Por que nesta ordem:* o score v2 precisa dos campos da fase 1, e o registro de interações precisa começar cedo para acumular desfechos.

### Fase 3: longo prazo (2–6 meses)
**Objetivo: score que aprende e redução da defasagem.**
1. Com cerca de 200 ou mais desfechos, calibrar os pesos pela conversão real (item 13) e revisar a cada trimestre.
2. Google Places em produção, se o piloto mostrar acerto e conversão que paguem o custo (item 10).
3. Avaliar Serpro para revalidar os top-N do dia (item 18) e cotar um feed diário de novos CNPJs (item 19), decidindo pelo **custo por lead convertido** medido na fase 2.
4. Integração por API com o CRM escolhido. WhatsApp Business API só para contatos com opt-in.
5. Contexto IBGE e PNCP no score (item 20).

*Por que por último:* são os itens pagos ou de maior esforço. Só se justificam quando os dados das fases 1 e 2 mostrarem onde está o gargalo (volume, velocidade ou qualidade do contato).

---

## 9. Decisões que dependem de você

- **Qual é o produto e o cliente ideal de cada vendedor?** Isso define as listas de CNAE e se MEI é alvo ou exclusão.
- Orçamento mensal para enriquecimento pago (Google Places, Serpro, feed diário).
- Canal principal de abordagem (WhatsApp manual, telefone, e-mail) e CRM de destino.
- Validação jurídica do LIA e do aviso de privacidade.

---

## 10. Fontes consultadas

- Receita Federal — [Metadados dos Dados Abertos do CNPJ](https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf) · [Dados Abertos](https://www.gov.br/receitafederal/pt-br/acesso-a-informacao/dados-abertos) · [dados.gov.br CNPJ](https://dados.gov.br/dados/conjuntos-dados/cadastro-nacional-da-pessoa-juridica---cnpj)
- Serpro — [Loja: Consulta CNPJ](https://loja.serpro.gov.br/consultacnpj) · [Documentação API](https://apicenter.estaleiro.serpro.gov.br/documentacao/consulta-cnpj/) · [Catálogo Conecta](https://www.gov.br/conecta/catalogo/apis/consulta-cnpj)
- Google Maps Platform — [Pricing](https://developers.google.com/maps/billing-and-pricing/pricing) · [Places data fields/SKUs](https://developers.google.com/maps/documentation/places/web-service/data-fields) · [Places policies](https://developers.google.com/maps/documentation/places/web-service/policies) · [Usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing) · [Woosmap — análise de preços 2026](https://www.woosmap.com/blog/google-places-api-pricing)
- APIs de CNPJ — [Comparativo Hub do Desenvolvedor 2026](https://blog.hubdodesenvolvedor.com.br/api-de-consulta-de-cnpj/) · [ReceitaWS](https://receitaws.com.br/) · [CNPJá preços](https://cnpja.com/en/pricing) · [OpenCNPJ](https://opencnpj.org/)
- Pagas — [Casa dos Dados preços](https://portal.casadosdados.com.br/precos) · [LeadJet sobre Casa dos Dados](https://leadjet.com.br/casa-dos-dados/) · [Econodata planos](https://prospecte.econodata.com.br/prospectar-planos-precos) · [LeadJet sobre Econodata](https://leadjet.com.br/alternativa-econodata/)
- Domínios — [Registro.br RDAP](https://registro.br/rdap/) · [Homehost sobre RDAP](https://www.homehost.com.br/blog/dominio/whois-rdap-protocolo-de-dominios/)
- IBGE — [API de serviços](https://servicodados.ibge.gov.br/api/docs/) · [API de agregados](https://servicodados.ibge.gov.br/api/docs/agregados?versao=3) · [SIDRA](https://sidra.ibge.gov.br/)
- PNCP — [Manual de consultas (espelho)](https://gist.github.com/Micael106/04a3e5515057ab11ea8797603682f0bd)
- WhatsApp — [Platform pricing](https://whatsappbusiness.com/products/platform-pricing/) · [Preços Brasil 2026 (Message Central)](https://www.messagecentral.com/blog/whatsapp-business-api-pricing-brazil): marketing ≈ US$ 0,0625 por mensagem, fonte secundária
- LGPD — [ANPD: Guia Legítimo Interesse](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia_orientativo_hipoteses_legais_tratamento_de_dados_pessoais_legitimo_interesse) · [Notícia ANPD](https://www.gov.br/anpd/pt-br/assuntos/noticias/anpd-lanca-guia-orientativo-sobre-legitimo-interesse) · [Speedio: LGPD na prospecção B2B](https://speedio.com.br/blog/lgpd-na-prospeccao-b2b-como-usar-dados-de-contato-dentro-da-lei-sem-travar-as-vendas/) · [Neoway: LGPD na prospecção](https://blog.neoway.com.br/lgpd-na-prospeccao/)

*Limitações: as tabelas de preço do Serpro e do CNPJá não puderam ser lidas automaticamente (HTTP 403/429). Os valores marcados como "fonte secundária" devem ser confirmados com o fornecedor antes de qualquer contratação.*
