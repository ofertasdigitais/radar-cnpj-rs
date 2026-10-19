# Plano: hospedagem independente do Radar no Cloudflare

## Escopo autorizado

Workers + banco do Radar na conta já autenticada, endereço workers.dev, sem domínio próprio e sem depender do computador local. Preservar os fluxos, contas, dados e visual atuais. Não modificar nenhum recurso, configuração, domínio, código ou banco da Starker.

O código funcional foi enviado para `origin/codex/local-qa-20261009` em `8990f89`. O D1 antigo do Radar foi exportado, conferido por SHA-256, copiado para a pasta de backup autorizada e excluído a pedido do usuário. O novo D1 exclusivo do Radar é `1f91e449-5b76-4daa-9989-afff59545456`; a aplicação funcional local não foi substituída. Não existe Worker antigo do Radar na conta consultada.

## Decisões

- Adaptar o backend para Workers/D1; não publicar apenas os assets nem usar Quick Tunnel como hospedagem.
- Preservar contratos HTTP/JSON usados pelo frontend atual. Usar a estrutura SQLite atual como referência, sem reduzir campos ou descartar histórico.
- Criar migrações e exportador de snapshot consistente em `data/`, sempre ignorado pelo Git. Separar DDL e carga de dados.
- Preservar isolamento por conta e propriedade dos contatos fictícios, funções administrativas, revisão de sessão, CSRF, limites e validação de dados.
- Não desabilitar o bloqueio de publicação enquanto faltar paridade ou houver teste relevante com falha.
- Ações remotas são exclusivas do agente principal. Revisões/implementações paralelas ficam restritas a arquivos de módulos e testes independentes.

## Contrato entre módulos

`src/runtime.ts` define `Env`, `Principal`, `Row`, `ApiError`, `json`, `bodyJson`, `queryRows`, `queryFirst`, `requireProfile`, `privateCompanyVisible`, `now` e `moneyCents`.

Cada módulo exporta `handleX(request, env, principal, url): Promise<Response | undefined>`. `undefined` significa que a rota não pertence ao módulo; erros previstos usam `ApiError`. Principal usa `accountId`, `username`, `role`, `expires`; administrador possui `role='admin'`. Todas as mutações e leituras verificam o dono no servidor. O frontend não decide autorização.

## Sequência

1. Guarda de destino e esquema atual em D1; snapshot/exportação com ensaio local.
2. Login, sessão/revogação e consultas oficiais/segmentações.
3. Tratamento de leads, valores, agenda, mensagens, BI e relatórios.
4. Administração, contas, FAQ e manutenção compatível.
5. Captação/recomendações/agendamento e qualificação, sem dependência silenciosa de executável local.
6. Testes de paridade em banco descartável e publicação controlada em recursos Radar.
7. Carga final consistente, conferência de contagens/integridade/ownership, testes externos e entrega da URL definitiva.

## Verificações e riscos

- D1 antigo não tinha os campos/tabelas atuais: cada rota precisa de teste, não apenas de compilação.
- Coletor Node/índice OSM e backup de arquivo SQLite não são transferidos copiando frontend: definir adaptações explícitas, sem aparentar sucesso inexistente.
- Não contratar plano/serviço adicional automaticamente. Validar limites antes de carga volumosa; não esgotar cotas compartilhadas da conta por suposição.
- Não restaurar snapshots antigos sobre dados mais recentes. Na virada, estabelecer um ponto de corte de gravações e preservar cópia consistente.
- Starker: consultas de inventário somente para identificar dependências; nenhuma mutação autorizada. O banco Starker tem outro UUID, não configurado em nenhum comando de migração Radar.

Tarefas e critérios: [todo.md](todo.md).

## Checkpoint — 19/10/2026

Worker atual publicado em `https://radar-cnpj-rs.radar-cnpj-rs-cloudflare.workers.dev`.
Banco completo conferido: 174 leads/715 eventos; snapshot de 19/10 sem alterações
lógicas desde a carga. Smoke externo passou para vendedor e administrador,
incluindo PDF, CSV, integridade, privacidade e revogação. Readiness atual aprovado.
O limite PBKDF2 da produção, ausente no workerd local, foi tratado preservando
SHA256/260k/salts/hashes existentes, com biblioteca fixada e vetor Python independente.
Falta concluir o GitHub e ativar/testar o workflow mensal na branch padrão.
Limitações estão em `docs/STATUS-20261019.md` e na Central de Ajuda.
