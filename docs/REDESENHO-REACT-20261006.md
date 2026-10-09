# Visão geral reconstruída em React — 06/10/2026

## Alteração visível no Radar

A tela **Visão geral** foi efetivamente substituída por uma aplicação React, dentro do Radar e da mesma sessão. A ilustração antiga de pontos e os blocos com larguras diferentes foram removidos. Não existe uma nova página avulsa.

- Inter como fonte única; controles de 15 px, textos de 15–16 px, títulos de seção de 23 px e indicadores de 40 px. Ajustes proporcionais em celular, sem reduzir textos para 8–10 px.
- Mesma linha de alinhamento, largura disponível e espaçamento de 16–24 px. Sidebar legível, com quebra de textos; drawer nas telas menores.
- Carmesim, painéis claros/escuros e contraste verificado. Animações discretas respeitam movimento reduzido.
- Busca, períodos, segmentações salvas, filtros, rankings clicáveis, abertura dos detalhes completos e atalhos para a fila de trabalho.
- Gráfico de aberturas por mês usa ECharts local e tem tabela alternativa. Rankings mantêm quantidade e percentual na mesma linha; não usam pontos decorativos.
- Exportação completa da segmentação foi preservada e movida para **Empresas → Exportar CSV**. PDF personalizado continua no BI/Painel de Leads.

## Três seções da visão geral

1. **Mercado e oportunidades:** dados RF do recorte, aberturas mensais, segmentos, municípios e empresas prioritárias.
2. **Minha operação:** leads, ações atrasadas, falta de próxima ação, contato, negociação, receita e velocidade do responsável selecionado. Usa todos os leads desse responsável; não aplica a janela de abertura RF aos indicadores comerciais. Valores financeiros preservam os centavos.
3. **Ferramentas e integrações:** estado consultado da captação e Serpro, explicação do fluxo e catálogo dos sete projetos integrados, com versões e links dos repositórios.

## O que está instalado versus o que está ativo

| Recurso | Situação e uso |
| --- | --- |
| React/ReactDOM | Entrada, visão geral e descoberta automática. **Não foi feita a migração integral de todas as telas**; as demais rotinas continuam no código existente. |
| Apache ECharts | Gráficos da visão geral e BI com dados das APIs existentes. |
| Crawlee | Coletor Node instalado para enriquecimento opcional de sites públicos, com limites e proteção do transporte. Não equivale a captação real confirmada. |
| OpenStreetMap/Overpass | Campanhas implementadas. A coleta real ponta a ponta ainda depende da disponibilidade da API pública; testes externos anteriores tiveram timeout/504. |
| libphonenumber-js | Formato/DDD/nono dígito. Não identifica automaticamente contas WhatsApp. |
| Papa Parse | CSV guiado opcional, com mapeamento, prévia e preservação de duplicados. |
| pdf-lib | PDF personalizado; geração validada, sem impressão HTML. |
| Lucide | Ícones de navegação consistentes. |
| Serpro | Credenciais e contratação pendentes no estado inspecionado. Não está incluída na assinatura Cloudflare. |
| Base44 | Contrato/ponte preparado em `integrations/base44_bridge.py`; não carregado automaticamente pelo servidor. Sincronização real exige configuração e validação no CRM. |

Captação: **Ferramentas → Descoberta automática → Criar campanha**. Defina cidade/categoria, habilite enriquecimento se desejar, escolha sob demanda ou diário e salve. Os contatos encontrados aparecem em **Contatos externos**, privados por conta. O servidor precisa estar ligado para rodadas diárias. Nenhuma campanha real foi criada/ativada nesta alteração.

## Preservação e validação

- O componente React não escreve no DOM dos filtros antigos. `RadarOverview` faz a ponte com as mesmas APIs e ações do Radar.
- Respostas antigas de carregamentos sobrepostos são ignoradas. Falhas têm mensagem e tentativa de recuperação; não ficam em loading infinito nem apresentam números anteriores como resultado de filtros novos.
- Gráficos e consultas comerciais são desligados ao sair da visão geral. Bibliotecas do gráfico são carregadas localmente sob demanda.
- Nenhuma tabela, conta, senha ou lead real foi alterado. QA usa SQLite temporário, separado do banco do usuário.
- Validação: 26 testes Chromium, cobrindo quatro larguras × dois temas, tabelas visíveis no celular, acessibilidade, filtros, fila de trabalho, detalhes, CSV, PDF e recuperação de erro. Mais cinco testes Node das ferramentas/PDF.
- Sem publicação em Workers/Pages. O túnel Cloudflare já existente continua ligado e reflete os arquivos locais; não foi criado outro túnel. A migração definitiva exige paridade das novas rotas/tabelas e execução separada do coletor Node.

Reprodução: `npm.cmd run build:react`, `npm.cmd run test:tools` e `npm.cmd run test:browser`. Para conferir no Radar: atualize com Ctrl+F5 e abra **Visão geral**.
