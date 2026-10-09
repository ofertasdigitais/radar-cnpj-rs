# Radar CNPJ: auditoria de produto e ferramentas

Pesquisa em 05/10/2026. Comparação funcional, não recomendação de compra ou promessa de resultado comercial.

## O que o mercado oferece e o que interessa ao Radar

O [Pipedrive](https://www.pipedrive.com/en/features/sales-reporting) organiza relatórios, metas e visões individuais de vendedores. O [HubSpot](https://www.hubspot.com/products/sales/sales-reports) destaca relatórios de receita, atividade e desempenho do funil. Isso orienta a comparação abaixo; não significa que esses recursos sejam gratuitos nesses produtos.

| Necessidade | Entrega local desta atualização | Próximo nível, ainda não implementado |
| --- | --- | --- |
| Organização diária | Fila com retornos vencidos, primeiro contato fora do prazo e negociação parada; prazos configuráveis por responsável | Notificações opcionais e agenda integrada |
| Segmentação | Campanhas de prospecção nas 21 áreas econômicas, CNAEs e município; segmentações/ICP salvos | Comparação de campanhas com custo de aquisição informado |
| Análise de resultado | Contato, conversão, pipeline ativo, receita fechada, tempo de contato/fechamento; cortes por campanha, segmento, persona e origem | Coortes históricas imutáveis, metas e evolução de receita por data de fechamento |
| Perdas | Motivos declarados e perdas sem justificativa destacadas | Análise de objeções e ações de recuperação |
| Rastreabilidade | Antes/depois dos campos, consulta de atividades por data e arquivo de histórico para futuras remoções de leads | Autor explícito por evento, restauração do lead e retenção configurável |
| Compartilhamento | PDF comercial por responsável/coorte/campanha e CSV com seleção de colunas | Relatórios agendados, sem expor dados de outros vendedores |

Recomendação: manter o Radar focado em descoberta, segmentação e rotina comercial. O item 7, integração com o CRM, foi excluído desta execução; os arquivos e recursos anteriores dessa integração não foram ampliados.

## Repositórios gratuitos avaliados

| Projeto / fonte primária | Uso possível | Decisão nesta execução |
| --- | --- | --- |
| [ReportLab](https://pypi.org/project/reportlab/) | Gerar documentos PDF em Python | Integrado localmente; versão fixada em requirements.txt. Sem API paga para gerar os relatórios |
| [Apache ECharts](https://github.com/apache/echarts) — Apache-2.0 | Gráficos com tooltip, zoom e seleção, sem precisar reconstruir o Radar em React | Candidato para evolução dos gráficos. Não adicionado automaticamente: primeiro definir indicadores e validar o ganho visual |
| [libphonenumber-js](https://github.com/catamphetamine/libphonenumber-js) — MIT, com material original Apache-2.0 | Metadados mais completos de países/DDD, análise e formatação de telefone | Candidato para substituir validações simplificadas. Formato válido não comprova WhatsApp |
| [Playwright](https://github.com/microsoft/playwright) — Apache-2.0 | Testes repetíveis de telas, formulários e navegadores | Candidato para uma suíte permanente. Nesta etapa: testes HTTP automatizados e inspeção no navegador disponível |
| [axe-core](https://github.com/dequelabs/axe-core) — MPL-2.0 | Auditoria automática de acessibilidade e parte dos problemas de contraste | Candidato de QA, não instalado no produto nem executado nesta auditoria; resultados automáticos não substituem inspeção humana |

Gratuito aqui significa ausência de licença comercial obrigatória para os usos considerados. Hospedagem, manutenção, mensageria, execução de jobs e obrigações das licenças continuam existindo. Preservar avisos de licença ao distribuir dependências e fixar versões antes de uma integração definitiva.

## Dados que não devem ser inventados

- CNAE não revela cargo do comprador, faturamento, quantidade de funcionários ou intenção de compra. Persona, origem, campanha e valores são declarados no tratamento do lead.
- Abrir uma conversa não comprova existência no WhatsApp; confirmação é registrada pelo vendedor. A revisão de formato é uma verificação distinta.
- Histórico antigo sem valores anteriores não pode ser reconstruído. O antes/depois começa nas próximas edições.
- O BI atual usa coorte por data de entrada, não receita reconhecida durante um mês. A próxima evolução deve separar aquisição, atividade e fechamento com filtros explicitamente diferentes.
- Percentuais por etapa representam a distribuição atual; não se afirma uma taxa histórica de transição entre etapas sem eventos suficientes.

## Caminho recomendado

1. Usar o fluxo atual, manter próximos passos/prazos preenchidos e registrar motivos de perda.
2. Definir meta comercial, origem e custo de campanhas para calcular produtividade e aquisição com base real.
3. Evoluir gráficos com ECharts apenas quando houver um indicador útil e ganho concreto de leitura.
4. Automatizar QA por dispositivo e acessibilidade antes de publicar uma nova versão.
5. Planejar a migração Cloudflare separadamente. O PDF desta versão usa o backend Python local; não é uma implementação para Workers. A implantação cloud exige uma implementação compatível ou serviço próprio, com custos e permissões avaliados antes.

Não foram contratados serviços, enviadas mensagens, consultados telefones externos ou publicados arquivos no Cloudflare.
