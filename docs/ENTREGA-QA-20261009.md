# Fechamento local e versionamento — 09/10/2026

## Escopo confirmado

1. QA: concluído; falhas da rodada anterior investigadas e corrigidas.
2. Cloudflare: aguardando. Não houve deploy nem migração remota.
3. Segurança: correções e testes locais concluídos; relatório histórico fechado.
4. Admin/FAQ: revisão final concluída, incluindo autorização e recuperação.

CRM/Base44 fica para outra versão. Sua estrutura atual permanece no projeto,
sem configuração de persistência real ou sincronização. A remoção para uma
edição comercial será feita posteriormente, não nesta entrega.

## O que houve com o QA

- Uma resposta antiga de consulta podia sobrescrever a campanha depois de
  **Pausar**. Controle de geração da requisição resolve a corrida; teste força
  a resposta antiga e confirma que o estado novo é preservado.
- A visão geral era testada com números fixos do seed, apesar de testes
  anteriores concluírem leads. Agora compara indicadores com a API real da
  base isolada, sem mascarar falhas de consistência.
- O teste de captura esperava apenas cinco segundos para um salvamento que
  aceita até quinze segundos na API. A espera acompanha o contrato.
- A tipagem de cabeçalhos no teste do Worker foi corrigida sem mudar o contrato.
- O smoke test da instalação apenas imprimia resultados e podia sair com
  código zero diante de uma rota quebrada. Agora retorna falha se a rota,
  restrição anônima, integridade ou disponibilidade de guias não passar.
- O gate do banco exige também perfis com proprietário; ausência de uma
  verificação obrigatória não é interpretada como sucesso. Quatro regressões
  novas cobrem esses gates.

## Validação local repetida

| Verificação | Resultado |
| --- | --- |
| Python | 106 testes aprovados |
| Chromium: Admin/FAQ/BI/leads/WhatsApp/captação, claro/escuro, 390–1920 px e tablet touch | 78 testes aprovados |
| JavaScript: BI, PDF, CSV e telefones | 8 testes aprovados |
| Contrato portátil do receptor (sem envio) | 2 testes aprovados |
| Coletor controlado, sem consulta externa real | 4 testes aprovados |
| Worker local | 7 testes aprovados e TypeScript aprovado |
| Taxonomia | 21 áreas e subcategorias verificadas |
| Rotas da principal | Admin/FAQ/arquivos/contatos 200; ajuda redireciona 303; anônimo 401 |
| Banco principal | integridade OK; zero relações inválidas, duplicidades, leads órfãos ou perfis sem proprietário |

Contagens após os testes: 133.067 empresas, 3 contas, 3 perfis, 166 leads e
668 eventos comerciais. Sem campanhas reais ativas ou em execução nessa
conferência. Admin recebeu 31 guias publicados, incluindo os administrativos.
Nenhum teste de navegador foi direcionado ao banco funcional.

O ensaio anterior de recuperação conferiu 34 tabelas; a base não foi restaurada
nem substituída. Dados de Marcos e a conta fictícia Radar permanecem separados.

## GitHub sem implantação

A publicação usa uma branch de código `codex/local-qa-20261009`, sem atualizar
`main` nem disparar publicação de hospedagem a partir dela. Não existe passo de
deploy no novo workflow `QA local`: ele instala dependências e executa testes
em ambiente descartável. O resultado remoto desse workflow deve ser conferido
no GitHub; a tabela acima registra as execuções locais.

Somente código, assets, licenças, testes e documentação entram no versionamento.
Bancos, backups, sessão, credenciais, `.env`, `.dev.vars`, logs e storage do
coletor são excluídos. Foi conferida a ausência da senha administrativa e do
segredo de sessão operacionais entre os arquivos candidatos a publicação.
**GitHub não é o backup do banco de leads.** O backup SQLite continua privado.

`.env.example` passa a recomendar produção, cadastro público desativado,
segredo obrigatório e Serpro automático desligado. Não alterou parâmetros da
instalação em execução. O README foi atualizado para explicar dependências,
execução, QA, segurança dos dados e bloqueios de hospedagem.

## Limites que continuam explícitos

- A revisão estática de segurança foi parcial (36 arquivos revisados no
  inventário inicial de 668 caminhos). Não é garantia de segurança total.
- Não houve consultas pagas, mensagens WhatsApp, coleta real externa ou envio
  ao CRM para validar aparência/QA.
- Cloudflare ainda exige paridade de schema/API/runtime e ensaio de migração.
- Docker não estava disponível para construir/testar a imagem nesta máquina.
- As validações no Chromium não substituem todos os navegadores e tablets físicos.

Detalhes: [Auditoria](AUDITORIA-RADAR-20261007.md),
[Admin](ADMIN-20261007.md) e [Ajuda](AJUDA-E-QUALIFICACAO-20261007.md).
