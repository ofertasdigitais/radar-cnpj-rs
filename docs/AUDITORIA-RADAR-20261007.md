# Radar CNPJ — auditoria iniciada em 07/10, atualizada em 09/10/2026

Fechamento posterior de QA, Admin/FAQ e versão para GitHub:
[Entrega de 09/10](ENTREGA-QA-20261009.md). Inclui quatro regressões adicionais
dos gates (106 testes Python); os resultados abaixo preservam a rodada original.

## Resultado local

Melhorias aplicadas à base funcional, sem publicação remota, envio ao CRM ou
ativação de consultas pagas. Visual preservado com camada `radar-polish.css`:
Inter, números tabulares, rubi/carmesim, relevo de botões, bordas, sombras suaves,
contraste claro/escuro e movimento reduzido. Cabeçalho móvel usa atalhos compactos.
Referências visuais: dashboard Efferd/21st.dev e layouts/editorial Awwwards;
nenhuma biblioteca de UI nova nem substituição dos fluxos existentes.

## Correções e validações

- Sessões distinguem bootstrap de conta; nome reservado não concede privilégio.
  Cookies antigos ambíguos são recusados, senha redefinida revoga sessão bootstrap.
- Limites de login por identidade canônica, incluindo aliases; tentativa contra
  outro nome não bloqueia usuários conhecidos que compartilham o túnel.
- Nenhuma adoção automática de perfil legado por nome/e-mail não verificado.
- CSV neutraliza fórmulas de texto na saída, sem alterar banco ou números.
- Worker preparado tem orçamento persistente D1 e limite real de bytes de corpo.
- BI exclui concluídos/suprimidos das filas ativas, mantém centavos e separa prazos
  vencidos, hoje e próximos dias. Gráfico não estima dinheiro sem registro.
- Captação ignora conta desativada e respostas antigas não desfazem uma pausa.
- Índice OSM e ponte CRM respeitam `RADAR_DATA_DIR`.
- FAQ ganhou explicações de acesso, leads concluídos/BI e implantação pendente.
- Docker inclui módulos Python e dependências necessárias; registro público e
  monitor Serpro desligados. Imagem não foi construída: Docker indisponível.

### Testes executados em bases isoladas

| Grupo | Resultado |
| --- | --- |
| Python: contas, permissões, admin, FAQ, recuperação, banco, leads e captação | 102 aprovados |
| Navegador Chromium: 390/768/1024/1920, ambos temas, tablet touch, PDF/CSV/FAQ/BI | 78 aprovados |
| Ferramentas JavaScript: BI, CSV, telefone e PDF com Inter incorporada | 8 aprovados |
| Receptor CRM portátil: assinatura, identidade, centavos e adulteração | 2 aprovados |
| Coletor: SSRF, robots e enriquecimento determinístico sem rede externa | 4 aprovados |
| Worker: sessão, isolamento, aliases, CSV, corpo e origem | 7 aprovados |
| TypeScript, build React, sintaxe PowerShell e Worker `--dry-run` | Aprovados |

O primeiro teste completo de navegador encontrou expectativas antigas de cinco
etapas após outros testes criarem leads concluídos, e uma espera insuficiente de
salvamento. Foram corrigidos para comparar com o contrato real e aguardar a API.
O novo teste de corrida força uma resposta antiga após a pausa; também passou.
Não houve alterações no banco operacional para fazer esses testes passarem.

### Banco operacional e backup

Em 09/10, antes do reinício: 133.067 empresas, 3 contas, 3 perfis, 166 leads e
668 eventos de histórico. Contagens podem mudar com o uso normal do vendedor.
Integridade `ok`, zero violações de chaves estrangeiras, duplicidades de CNPJ,
leads órfãos, perfis sem dono e empresas ativas atribuídas a mais de um perfil.
Consultas de histórico e leads usam os respectivos índices.

Cópia consistente:
`backup-testes/auditoria-20261007/radar-final-20261009.sqlite`.
Recuperação ensaiada em arquivo temporário: **34 tabelas e seus registros
conferidos**, zero relações inválidas. Nunca substituiu a base funcional.
`radar-pre.sqlite` e `original/` preservam o estado anterior à auditoria.
Backups contêm informações privadas; ficam fora do Git.

Conta de apresentação `Radar`: 24 leads fictícios, 97 movimentos, UF ZZ, origem
de demonstração, sem dados de Marcos. Login e painel conferidos após reinício.
O reinício preservou o processo do túnel; não gerou outro endereço público.

## Limites da auditoria de segurança

Seis defeitos do snapshot anterior foram corrigidos e testados localmente.
O relatório canônico de segurança preserva os defeitos como **históricos
corrigidos**, não como prova de vulnerabilidade ainda aberta.
Cobertura estática é **parcial**: 36 arquivos integralmente revisados para
segurança no inventário inicial de 668 caminhos. Testes amplos não equivalem à
leitura integral de todo o código. Não houve pentest da implantação remota, WAF,
ACL Windows ou validação de cópia fora deste computador. Não é garantia de 100%.

## CRM Base44: estrutura pronta, integração ainda desligada

Saída por conta/perfil, prévia por padrão e envio somente com `--send`.
Receptor portátil valida assinatura e mapeamento; persistência real precisa do
esquema do CRM e de implementação atômica idempotente, com proteção de versões.
Veja `INTEGRACAO-BASE44.md`. Não existe sincronização automática ativada.

## Cloudflare: preparação não equivale a migração pronta

O Worker existente é legado. A verificação encontrou 12 lacunas de tabela/esquema,
incluindo histórico, mensagens, valores, datas, WhatsApp, supressões, captação e FAQ.
Também falta paridade de rotas/admin/BI e runtime de coletores.
O exportador antigo agora **recusa bases modernas antes de gerar lotes**, para
evitar perda silenciosa. `release_readiness.py --cloudflare` retorna 2 por
projeto; `npm run deploy` e migração remota usam essa trava. Não contorne com
Wrangler direto para publicar. O dry-run usado no QA apenas construiu o pacote.

Sequência segura para publicação futura:

1. Definir conta/ambiente staging separado e D1 novo; não reutilizar o destino
   histórico em `wrangler.jsonc`. Modelo em `wrangler.staging.example.jsonc`.
2. Completar Worker/D1 e exportador para TODAS as tabelas, campos e fluxos atuais.
3. Importar backup consistente em staging; comparar registros, donos, centavos,
   históricos, metas, bloqueios, mensagens, FAQ e permissões, sem sobrescrever a origem.
4. Executar os fluxos modernos e testes de isolamento no destino, incluindo Radar
   e Marcos. Testar exportação e recuperação do D1.
5. Definir runtime separado para Crawlee/índice OSM: copiar assets não executa Node
   ou Python no Worker. Manter erros de fonte explícitos; não inventar contatos.
6. Confirmar segredos, registro público desativado, retenção, backup e limites
   de consumo; então realizar corte autorizado e plano de retorno.

Nenhum serviço pago foi contratado ou acionado. Consultas externas reais do
OSM/Crawlee e persistência Base44 não foram usadas como prova nesta rodada.
