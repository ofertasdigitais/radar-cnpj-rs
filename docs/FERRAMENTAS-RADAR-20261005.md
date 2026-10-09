# Radar: ferramentas integradas e relatório personalizado

Implementação local em 05/10/2026. Nenhuma publicação ou migração para Cloudflare, contratação de serviço ou ampliação da integração CRM.

## O que foi integrado de verdade

| Projeto | Versão fixada | Aplicação no Radar |
| --- | --- | --- |
| [Apache ECharts](https://github.com/apache/echarts) | 6.1.0 / Apache-2.0 | Gráficos SVG interativos no BI: etapas, contatos, entradas semanais, prazos e tempo parado. Tooltip, redimensionamento, tema e tabela acessível dos valores |
| [Lucide](https://github.com/lucide-icons/lucide) | 1.52.0 / ISC | Ícones consistentes no menu, preservando os rótulos e o contraste do Radar |
| [libphonenumber-js](https://github.com/catamphetamine/libphonenumber-js) | 1.13.14 / MIT | DDD e formato brasileiros, telefone internacional e sugestão explícita de nono dígito; não comprova existência no WhatsApp |
| [PapaParse](https://github.com/mholt/PapaParse) | 5.7.0 / MIT | CSV com separador detectado, mapeamento de colunas, prévia, zeros iniciais e acentos preservados. Modelo exportado protege células de fórmula |
| [pdf-lib](https://github.com/Hopding/pdf-lib) + fontkit | 1.17.1 / 1.1.1 / MIT | PDF vetorial direto no navegador, com fonte Inter incorporada, sem imprimir uma página HTML e sem API de geração paga |
| [Inter](https://github.com/rsms/inter) | 4.1 / OFL-1.1 | Fonte estática oficial Regular/Bold no PDF; mesma família usada na interface |
| [Playwright](https://github.com/microsoft/playwright) | 1.63.0 / Apache-2.0 | Testes repetíveis em navegador Chromium, usando uma base SQLite temporária |
| [axe-core](https://github.com/dequelabs/axe-core) | 4.14.0 / MPL-2.0 | Auditoria automatizada das ferramentas novas; não carregado no produto |
| [BrasilAPI](https://github.com/BrasilAPI/BrasilAPI) | Serviço público externo, sem versão controlada pelo Radar | Consulta opcional de CEP. Só o CEP digitado é enviado, sem cookies; nada é gravado automaticamente |

Não se copiou um CRM inteiro nem se substituiu o Radar por outro framework. As bibliotecas foram integradas ao fluxo existente, com `package-lock.json`, avisos de licença e SHA-256 dos bundles em `static/vendor/manifest.json`.

Bibliotecas são servidas localmente, sem CDN em execução. Núcleo de telefone/CSV/ícones: aproximadamente 220 KB; gráficos: 584 KB; PDF: 1,38 MB. Gráficos e PDF carregam apenas quando usados. Inter TTF é buscada ao gerar o PDF; licenças de fontes estão em static/fonts.

## Fluxos novos

- **Ferramentas > Contatos externos:** cadastro manual ou CSV de indicação, evento ou fonte própria, com empresa, nome, telefone, e-mail, cidade, CNPJ opcional, campanha, persona, origem, site, notas e situação.
- Lista paginada de 50 contatos, pesquisa e edição. Importação atômica: um erro impede o lote inteiro. Arquivos de até 2 MB e 500 linhas; duplicados iguais na mesma conta são ignorados, sem sobrescrita.
- Contatos ficam em `prospect_inbox`, isolados por conta. Nem o administrador vê automaticamente os contatos externos de outra conta. As métricas oficiais do BI continuam somente com leads vinculados no Painel de Leads.
- Se houver CNPJ existente, **Buscar no Radar** abre a empresa, permitindo o vínculo pelo tratamento normal. Não são criados CNPJs oficiais ou empresas fictícias automaticamente. Contatos sem CNPJ ficam na lista privada e podem ser tratados ali.
- **Ferramentas > Revisar telefone:** mostra formato, DDD e possível número antigo sem 9. No botão WhatsApp dos leads oficiais, sugestão de correção exige confirmação e não altera o original silenciosamente.
- **Ferramentas > Pesquisa e CEP:** monta links de pesquisa para Maps, site e LinkedIn. São links externos acionados pelo vendedor, não scraping ou enriquecimento automático. Consulta CEP tem prazo de 8 segundos e tratamento de indisponibilidade.
- **Ir para… / Ctrl+K:** navegação por busca de módulo. BI tem atalhos para suas seções, evitando percorrer o painel inteiro.

## PDF com design Radar

No Painel de Leads, abra **Rotina do vendedor e relatórios > Personalizar relatório PDF**. No BI, use **Personalizar PDF deste recorte**.

Escolha título, apresentação/empresa, nome de arquivo, notas e seções. Gere a prévia e baixe. Resumo executivo obrigatório; desempenho, fila e qualidade são opcionais. O responsável e o recorte seguem a autorização da API. O documento usa cabeçalho preto/carmesim, Inter, cartões de indicadores, gráfico por etapa, tabelas paginadas e rodapé privado numerado.

O exemplo em `output/pdf/radar-modelo-personalizado.pdf` usa **96 leads fictícios**, nunca dados da base real. A exportação antiga `/api/commercial-report.pdf` permanece por compatibilidade; os botões da interface usam o novo estúdio e pdf-lib.

## Verificação e limites

- 35 testes Python: importação, validação, duplicados, propriedade por conta, edição, persistência e regressões anteriores.
- 5 testes Node: telefone, CSV, URLs, PDF vazio, título longo, acentos e glifos ausentes.
- 10 testes Chromium: fluxo completo CSV/edição/BI/download, larguras 390/768/1024/1920, claro/escuro e acessibilidade da área nova. Zero falhas na rodada final.
- O ajuste de contraste do WhatsApp externo eliminou a violação séria encontrada por axe. Não equivale a certificação de acessibilidade de todas as telas.
- Migração ensaiada numa cópia consistente: empresas, contas, perfis, leads, histórico e configurações comerciais preservados integralmente; integridade e chaves estrangeiras aprovadas.
- Backup anterior à nova tabela: `data/qa-backups/radar-antes-ferramentas-20261005.sqlite`. Contém dados privados: não publicar.
- Não foi prometido “100% sem bugs”: não há teste de carga, de todos os tablets físicos, de Firefox/WebKit nem garantia de disponibilidade da BrasilAPI.
- Importação externa registra dados declarados. Não estima faturamento, empregados ou intenção de compra; não confirma WhatsApp, não envia mensagens e não consulta uma API paga.
- A lista externa ainda não tem restauração/histórico detalhado, tarefas financeiras ou BI próprio. Para entrar no funil oficial, é preciso vincular uma empresa já existente.

## Repetição e Cloudflare

```powershell
npm.cmd ci --ignore-scripts
npm.cmd run build:tools
npm.cmd run test:tools
npx.cmd playwright install chromium
npm.cmd run test:browser
python -m unittest discover -s tests -q
python tools/db_qa.py
python tools/validate-tools-migration.py
```

O teste de navegador sobe apenas `tools/qa_preview.py` na porta 18000, com banco temporário e sem iniciar os sincronizadores fiscais. Não usa `npm run dev`.

O novo PDF funciona no navegador e não depende do Python para desenhar o documento. **Isso não torna o backend atual automaticamente compatível com Cloudflare**: antes de publicar, portar `/api/commercial`, `/api/prospects` e suas regras de propriedade para Worker/D1, aplicar a migração equivalente, verificar sessões e testar a paridade. As bibliotecas/front-end já são arquivos estáticos portáveis. Não publicar a pasta data, backups ou credenciais.
