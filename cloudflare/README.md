# Radar CNPJ RS no Cloudflare

## Bloqueio de publicação — auditoria de 07/10/2026

**Este Worker é uma versão legada, não uma cópia funcional do Radar atual.**
Não execute os antigos comandos de importação/publicação para substituir produção.
`npm run readiness` compara o esquema em memória, lê o SQLite em modo somente
leitura e retorna código 2 enquanto faltar paridade. `npm run deploy` e a migração
remota passam por essa trava; chamar Wrangler diretamente a contorna.
Veja `../docs/AUDITORIA-RADAR-20261007.md` para a sequência de migração e bloqueios.
O arquivo `wrangler.staging.example.jsonc` é um modelo com IDs inválidos de
propósito. O destino antigo em `wrangler.jsonc` foi preservado, não reutilizado.
Nenhuma publicação ou cobrança foi feita nesta auditoria.

Esta pasta contém a versão Cloudflare do Radar. A aplicação local em Python e o
banco `data/radar.db` continuam sendo a fonte operacional até a migração remota
ser validada.

Arquitetura:

- Cloudflare Worker para HTML, assets, autenticação e API;
- Cloudflare D1 para empresas e estado comercial;
- isolamento obrigatório por `owner_id` em toda leitura e mutação comercial;
- cadastro público desativado por padrão;
- endereço fixo gratuito em `workers.dev`.

Nunca publique `radar.db`, credenciais DPAPI, segredos de sessão, dumps SQL com
dados reais ou arquivos de importação no Git.

## Registro histórico de publicação (não revalidado em 07/10/2026)

- URL fixa: <https://radar-cnpj-rs.radar-cnpj-rs-cloudflare.workers.dev>
- ambiente: Cloudflare Workers + Static Assets + D1;
- cadastro público: desativado;
- carga inicial: 9.012 empresas, 2 contas, 2 perfis comerciais e 12 vínculos;
- base local preservada: 133.042 empresas.

A sincronização cadastral e o monitoramento contínuo ainda não foram migrados
para o Worker. Esses comandos retornam bloqueio explícito no ambiente Cloudflare
para não aparentarem uma atualização que não ocorreu.

## Validação local

```powershell
npm install
npm run check
npm test
npx wrangler deploy --dry-run
```

## Preparação da carga D1

O plano gratuito do D1 aceita 100.000 linhas gravadas por dia, contando também
as atualizações dos índices. Por isso, a carga inicial gratuita é limitada às
9.000 empresas mais recentes, acrescidas de qualquer empresa já presente em
uma carteira. O banco local completo não é modificado.

```powershell
python .\scripts\export_d1.py
```

Use `--company-limit 0` para gerar a carga integral para validação local ou para
um ambiente cuja franquia comporte a importação. Cada execução cria um novo
diretório ignorado pelo Git em `data/cloudflare-import` e produz um manifesto
com contagens e hashes.
