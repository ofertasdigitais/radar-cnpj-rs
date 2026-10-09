# Integração Radar CNPJ → CRM Base44

## Estado em 09/10/2026

O contrato de saída e um adaptador local estão em `integrations/base44_bridge.py`.
O adaptador lê um lead de uma conta e perfil específicos em modo somente leitura.
Por padrão, apenas imprime uma prévia JSON. Nenhum envio automático foi ligado.
O Radar em execução e a versão Cloudflare não carregam esse módulo.

Atualização de 07/10/2026: o `/admin` do servidor Python permite preparar a URL
e o segredo da ponte. O comando abaixo lê essa configuração no banco informado
por `--db`; variáveis de ambiente têm prioridade para o segredo. A interface não
inicia envios. O receptor no CRM e a sincronização automática continuam pendentes.

O núcleo receptor portátil está em `integrations/base44-receiver.mjs`, sem SDK
nem chamadas externas. Valida assinatura, bytes reais, contrato, centavos,
identidade e mapeamento explícito de conta/perfil. Seus testes locais passaram.
Sem `persistAtomic`, responde 503: **não simula uma integração concluída**.
O adaptador de saída recusa contas inativas e leads marcados como Não contatar,
restringe o destino a HTTPS Base44 e recusa redirecionamentos.

Para ativar, a função real precisa fornecer `secret`, `owners` e
`persistAtomic({event,crmOwnerId,idempotencyKey})`. A persistência deve ser
atômica por `external_id`, rejeitar versões antigas e preservar isolamento do
responsável. Antes de ligar qualquer envio, ensaie criação, repetição do mesmo
evento, atualização mais nova, rejeição de atualização antiga e dono desconhecido
com **um lead fictício**. Nenhuma função foi instalada no CRM nesta auditoria.

## Contrato v1

Evento `lead.upsert`, com `external_id` estável no formato
`radar:{account_id}:{profile_id}:{cnpj}`. Os valores monetários são inteiros em
centavos. O documento inclui `owner`, `company`, `contact`, `commercial` e
`source_updated_at`. O Base44 deve preservar esse identificador e fazer upsert,
não criar um lead novo a cada recebimento.

A função receptora no Base44 deve:

1. Receber `POST` por HTTPS.
2. Ler os bytes exatos do corpo antes de interpretar JSON.
3. Validar `X-Radar-Timestamp` com tolerância máxima de 5 minutos.
4. Calcular HMAC-SHA256 sobre `<timestamp>.<corpo UTF-8>` usando o segredo
   compartilhado e comparar em tempo constante com `X-Radar-Signature`.
5. Validar `contract_version=1`, `event_type=lead.upsert`, CNPJ, IDs de conta e
   perfil, campos e limites de tamanho.
6. Mapear `radar_account_id` e `radar_profile_id` para o usuário responsável no
   CRM; rejeitar IDs desconhecidos. Nunca confiar no nome como identidade.
7. Procurar pelo `external_id`; atualizar ou criar uma única entidade de lead.
   Para evitar sobrescrever mudanças mais novas, comparar `source_updated_at`.
8. Retornar JSON com `external_id`, `crm_lead_id`, `status` e `source_updated_at`.

O nome real da entidade e o mapeamento das etapas no Base44 ainda dependem do
projeto CRM. A função não deve usar login pessoal do Marcos. Operações de
serviço do SDK ficam dentro da função hospedada no Base44.

## Prévia local

Executar a partir da raiz do projeto, com IDs existentes:

```powershell
python -m integrations.base44_bridge --account-id CONTA --profile-id PERFIL --cnpj 11222333000181
```

O comando imprime dados do lead no terminal. Não compartilhe essa saída
publicamente. Para enviar, após criar e testar a função receptora, configure
`RADAR_BASE44_ENDPOINT` e `RADAR_BASE44_SECRET` como variáveis de ambiente e
adicione `--send` ao comando. A URL deve usar HTTPS e o segredo deve ter pelo
menos 32 caracteres. A chave não deve ir para Git, navegador, CSV ou screenshots.

## Pendente para completar a integração

- Link do editor do CRM Base44, nomes e campos das entidades, e acesso para
  configurar uma função e um segredo.
- Mapa `account_id/profile_id` do Radar → usuário responsável no CRM.
- Regras de etapa, resultado e valores no CRM.
- Estado de sincronização por conta/perfil/CNPJ no armazenamento da implantação
  escolhida, com ID remoto, última versão, tentativas e erro. Essa parte será
  implantada junto do fluxo definitivo, após decidir se o Radar operacional
  seguirá no Python/SQLite ou no Worker/D1.
- Botão de envio, processamento em lote, retentativa e reconciliação, após a
  função receptora estar testada com lead fictício.

Não usar o arquivo CSV como prova de integração automática. A exportação atual
é útil para importação manual enquanto o contrato do CRM é mapeado.
