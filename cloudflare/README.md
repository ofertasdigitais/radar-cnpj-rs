# Radar CNPJ RS no Cloudflare

## Publicação atual — 19/10/2026

[Radar online](https://radar-cnpj-rs.radar-cnpj-rs-cloudflare.workers.dev) ·
[Validações e limites](../docs/STATUS-20261019.md).

`wrangler.jsonc` e `wrangler.current.jsonc` apontam ao entrypoint `src/worker-current.ts`
e às migrações `migrations-current/`. `src/worker.ts`, `migrations/` e
`scripts/export_d1.py` são históricos: não usar para atualizar a produção atual.

A aplicação local e `data/radar.db` foram preservados. Não há sincronização
bidirecional: os novos lançamentos devem ser feitos na versão online.

Arquitetura:

- Cloudflare Worker para HTML, assets, autenticação e API;
- Cloudflare D1 para empresas e estado comercial;
- isolamento obrigatório por `owner_id` em toda leitura e mutação comercial;
- cadastro público desativado por padrão;
- endereço fixo gratuito em `workers.dev`.

Nunca publique `radar.db`, credenciais DPAPI, segredos de sessão, dumps SQL com
dados reais ou arquivos de importação no Git.

## Isolamento de destino

Worker `radar-cnpj-rs`, D1 `radar-cnpj-rs`, UUID `1f91e449-5b76-4daa-9989-afff59545456`.
Não reutilizar binding, rotas ou recursos da Starker. O plano Workers Paid existente
foi confirmado pelo proprietário; os recursos são separados, mas franquias e
eventuais excedentes de cobrança são compartilhados na conta Cloudflare.

## Validação local

```powershell
npm ci --ignore-scripts
npm run check
npm test
npx wrangler deploy --dry-run
```

`npm run readiness` verifica integridade em modo somente leitura, paridade de todas
as tabelas, destino exclusivo, TypeScript e testes do Worker atual/legado em bancos
temporários. Não prova, sozinho, que segredos, rede ou pipeline remoto funcionam.

```powershell
python .\scripts\prepare_current.py --source ..\data\radar.db --output ..\data\NOVA-PASTA-PRIVADA
```

Esse comando cria snapshot consistente e manifesto de todas as tabelas, DDL e
carga separados, sem alterar a origem. A carga inicial já foi realizada: **não
reimportar o snapshot em produção**, pois isso pode conflitar com dados mais novos.
Para nova migração, usar banco vazio isolado, ensaiar a restauração e conferir
contagens, hashes, relações e propriedade antes de qualquer virada.

## Receita mensal e captação

O workflow público `.github/workflows/receita-cloudflare.yml` verifica a competência
diariamente às 09:23 UTC (06:23 em São Paulo), e também aceita execução manual.
Usa apenas `RADAR_WORKERS_URL` e `RADAR_RECEITA_IMPORT_SECRET`. Nunca cadastrar
token da conta Cloudflare nesse workflow. O endpoint aceita somente campos oficiais
do RS e não altera leads, contas, valores ou histórico. Só publica a competência
depois de conferir lotes e catálogo CNAE; não promete rollback dos campos públicos
de lotes anteriores se a execução falhar.

O GitHub pode desativar o agendamento após 60 dias sem atividade. Falhas da Receita,
tempo máximo do runner e indisponibilidade de fontes devem ser acompanhados em
Actions e no estado de sincronização. O botão local de iniciar carga não dispara
GitHub Actions: para antecipar, usar Actions → Receita mensal → Run workflow.

Campanhas de captação usam Overpass/OpenStreetMap público e cron que verifica os
horários configurados. Sem campanhas configuradas não há captura automática.
Crawlee, índice OSM em disco e backup em pasta Windows não executam no Worker.
Serpro continua desativado para não gerar custos. Exportação D1/Time Travel e ensaio
de recuperação são feitos pelo administrador no fluxo Cloudflare, não como arquivo
SQLite local do painel.
