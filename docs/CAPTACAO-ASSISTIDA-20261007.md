# Recomendações automáticas por conta

Implementação local em 07/10/2026. Nenhum serviço pago, CRM, deploy, IA, push ou envio automático de WhatsApp foi ativado.

## Configurar

1. Recarregue o Radar com Ctrl+F5 e abra **Ferramentas → Descoberta automática → Criar campanha**.
2. Defina nome, município do RS e categoria. O perfil comercial opcional é um rótulo da estratégia, não um filtro de faturamento ou previsão de compra.
3. Em **Frequência**, escolha **Automática · até 3 horários por dia**. O padrão é 08:00, 13:00 e 17:00. É possível usar de um a três horários, com pelo menos uma hora entre eles.
4. Escolha os filtros de telefone/site e o enriquecimento Crawlee se desejar. Salve.
5. Use **Pausar** para suspender a campanha e **Ativar** para retomá-la. Coleta manual continua disponível.

Os horários seguem o relógio local do servidor. O agendador verifica a fila aproximadamente a cada minuto; concorrência e cotas podem atrasar rodadas. O computador e o Radar precisam estar ligados. Após uma parada, executa no máximo uma rodada vencida por campanha e calcula o próximo horário futuro, sem disparar todas as rodadas perdidas.

Limites compartilhados: até seis rodadas por conta/24h, 30 globais/24h, uma coleta simultânea e um minuto entre consultas. Até 50 estabelecimentos por rodada, dez sites e três páginas por site. O administrador pode reduzir limites. Várias campanhas não multiplicam a franquia; três horários configurados não garantem três rodadas para cada campanha.

## Tratar recomendações

- A seção **Recomendações para sua análise** tem **Para analisar**, **Selecionadas** e **Descartadas**, com paginação de 50 itens.
- Confira o motivo, a cidade, a categoria e os contatos publicados. Não representa interesse de compra ou WhatsApp confirmado.
- Selecione individualmente ou em lote. **Guardar seleção** não cria lead ativo nem tarefa.
- Em **Selecionadas**, **Tratar contato** abre a busca na lista externa. O encaminhamento ao Painel de Leads continua exigindo conferência e vínculo a um CNPJ existente.
- **Descartar** encerra a sugestão; não remove o contato externo nem seu histórico. O mesmo registro OSM já descoberto não volta como nova recomendação.
- Coleta não sobrescreve edições do vendedor. Pausar ou editar uma campanha em execução impede a gravação de seus resultados desatualizados.
- Recomendações surgem somente para contatos novos de rodadas posteriores à implementação; não reclassifica contatos antigos automaticamente.

## Avisos

O sino **Recomendações** aparece no topo do Radar, em todas as suas seções. Há um resumo persistente por rodada com novos contatos; rodadas sem novidades, falhas ou duplicados não geram aviso de sucesso. O contador consulta a conta autenticada aproximadamente a cada minuto enquanto a página estiver visível.

Abrir **Ver recomendações** marca aquele aviso como lido e leva à fila. A lista apresenta até 30 avisos, com os não lidos primeiro; é possível marcar os avisos exibidos como lidos. Desmarcar **Receber avisos de novas recomendações** silencia avisos futuros da conta, sem pausar campanhas, apagar recomendações ou retirar históricos existentes. São avisos internos, não notificações do sistema operacional.

## Ajuda e preservação

Três guias publicados na Central de Ajuda explicam horários, análise/avisos e índice local. Artigos editados anteriormente não são substituídos.

Migração aditiva: campos de horários/perfil/revisão nas campanhas, identificação do horário nas rodadas e três tabelas privadas de recomendações, avisos e preferências. Sem substituir o banco ou seus leads. Revisões impedem sobrescrita de decisões concorrentes; lotes são validados integralmente antes de salvar.

Backup anterior: `backup-testes/captacao-assistida-20261007-144039/radar-pre.sqlite`. Código anterior em `original/`, ensaio em `rehearsal.sqlite`. Não restaurar esse banco automaticamente: uma restauração descartaria trabalho comercial posterior ao backup.

Antes de reiniciar, foi criada outra cópia consistente: `radar-pre-activation.sqlite`, na mesma pasta. Após ativar a principal, as colunas e linhas anteriores das 31 tabelas foram comparadas por SHA-256 com essa cópia: nenhum dado preexistente alterado. Preservados 133.043 empresas, 118 leads comerciais, 452 eventos e duas contas. Integridade `ok`, zero violações de relações. Apenas as estruturas novas e três guias com sua marca de inicialização foram acrescentados.

## Evidências de validação

- Ensaio com backup real: dados anteriores das 31 tabelas preservados, integridade `ok`, zero violações de relações e três guias novos, sem sobrescrever artigos anteriores.
- Coleta local real trouxe 50 restaurantes de Porto Alegre em SQLite temporário. Nenhuma empresa fiscal ou contato real de teste inserido na principal.
- Testes cobrem agendamento, atraso sem rajada, cotas, pausa, concorrência, deduplicação, silêncio, seleção em lote, paginação, autenticação e isolamento entre vendedores.
- Navegador usa banco temporário e respostas de recomendações/notificações controladas. Não cria campanhas na principal. Layout e acessibilidade automatizada verificados em 390, 768, 1024 e 1920 px, temas claro/escuro; não substitui teste em tablet físico.
- Resultado final: 87 testes Python, 28 de navegador, seis de telefone/CSV/PDF e quatro do coletor aprovados. Inclui regressão da baixa de leads e da Central de Ajuda.
- Principal reiniciada e `/healthz`, recomendações, avisos, captação e três novos guias conferidos. Não criamos campanhas de negócio automaticamente: o vendedor ainda precisa escolher cidade/categoria e horários; nenhum segmento foi presumido.
