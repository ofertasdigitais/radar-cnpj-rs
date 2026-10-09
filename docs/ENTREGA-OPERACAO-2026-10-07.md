# Radar — pacote operacional local

## Onde usar

- Painel de Leads → Agenda e retornos: vencidos, hoje, próximos dias, sem agendamento e busca por empresa/CNPJ/telefone. Registrar contato salva resultado, nota histórica e retorno em uma transação. Mostrar mais permite percorrer a seleção completa.
- BI comercial → Entradas, contatos e fechamentos: recorte por datas, comparação de igual duração, evolução diária em gráfico e tabela; metas mensais privadas de receita, contatos e vendas.
- Agenda → Não contatar: motivo obrigatório, retirada da agenda e do CSV de leads, bloqueio do botão WhatsApp. O bloqueio acompanha a conta do responsável, inclusive quando um administrador gerencia a ficha. Contatos externos identificados pelo CNPJ ou vínculo também respeitam o bloqueio. Não bloqueia contatos feitos fora do Radar.
- /admin → Banco e manutenção: backup diário, pasta de segunda cópia, integridade e ensaio de recuperação.
- Central de Ajuda: quatro novos guias sobre agenda, bloqueios, resultados/metas e segunda cópia. Artigos previamente editados não são substituídos.

## Contratos dos indicadores

Entradas são contadas pela inclusão no painel. Contatos são registros efetivos e mudanças de resultado no histórico; abrir WhatsApp não comprova envio nem resposta. Fechamentos usam a data de fechamento dos leads atualmente Convertidos, incluindo entradas anteriores ao recorte. Datas antigas ausentes não são inventadas. Reaberturas e alterações posteriores não constituem contabilidade ou estornos.

Metas são objetivos definidos pelo usuário. O progresso considera o mês escolhido, independentemente do recorte de comparação. Não são previsões de receita. Valores monetários são armazenados em centavos.

Edições rápidas usam revisão do registro; a ficha completa usa a versão carregada. Uma gravação concorrente desatualizada recebe 409, sem sobrescrever a alteração mais recente. O vendedor deve reabrir ou atualizar a ficha para conferir os dados atuais.

## Backups e preservação

Antes da migração: `data/admin-backups/radar-20261007-104000-a7b812c3.sqlite`.

A migração foi ensaiada em cópia temporária: nenhuma tabela comercial existente alterada, artigos anteriores preservados, quatro novos guias adicionados, integridade aprovada e nenhum vínculo inválido. Nenhum lead fictício foi inserido na base de uso.

Backup conferido: `radar-20261007-104346-81953c8a.sqlite`, 62.980.096 bytes. Segunda cópia em `C:\Users\Suporte\Desktop\monitor definetive`. SHA-256: `63914876d0ad6aa3d845ca8e9cabe992f3bae6ab6ae578a89bb65e3a9b691b1b`.

O ensaio de recuperação abriu uma cópia temporária e comparou 31 tabelas; nenhum vínculo inválido. Não restaurou nem substituiu a base em uso. Os backups anteriores não foram apagados.

A pasta escolhida continua no mesmo computador: não é backup externo. A verificação de hash confirma a cópia de arquivo, não uma sincronização com nuvem. Backup diário exige servidor ligado e espaço disponível; não há retenção destrutiva automática.

## Validações

- Backend: 67 testes aprovados, incluindo propriedade de contas, parâmetros, contatos, CSV, datas, metas, supressão, restauração, falhas de cópia, agendamento diário e concorrência.
- Navegador: bateria completa com 58 testes, 31 reexecutados após ajustes finais e um teste adicional de touch aprovado. Agenda e BI testados em 390×844, 768×1024, 1024×768 e 1920×1080, temas claro e escuro. Touch, rotação e limite de colunas exercitados em contexto emulado. Testes de acessibilidade automatizados sem falhas graves/críticas nos componentes novos.
- Ferramentas: seis testes de telefone/CSV/PDF; três do coletor Crawlee.
- Desempenho: agenda e métricas de 10.000 leads em aproximadamente 0,44 s em SQLite temporário nesta máquina; não é promessa de desempenho em outra hospedagem.
- Base em uso: integridade aprovada, sem CNPJ duplicado, leads órfãos ou perfis sem proprietário. Dados de uso podem continuar mudando pelo trabalho normal dos vendedores.
- Responsividade em navegador emulado, não certificação em tablet físico. A revisão visual corrigiu um cabeçalho excessivamente alto no BI em orientação vertical.

## Captação: limites observados

O Crawlee leu uma página pública real (`example.com`) usando o transporte protegido. Extração de telefone/e-mail/CNPJ e respeito ao robots.txt também foram testados com conteúdo controlado. Isso não comprova que todos os sites comerciais permitem coleta.

As consultas reais ao OpenStreetMap não concluíram: timeouts nas duas instâncias e falha HTTP em uma consulta mínima. Portanto não foi possível certificar uma campanha real completa nesta rodada. Não foram inventados resultados nem importados contatos parciais como sucesso.

Foi acrescentada uma instância alternativa, limites de tamanho/tempo e mensagem explícita. HTTP 429 não é contornado por rotação de instância. A consulta de campanha continua limitada e respeita o cache e as cotas locais existentes. As fontes públicas não oferecem disponibilidade garantida.

Referências dos endpoints: [instâncias públicas do Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances) e [regras de uso dos recursos compartilhados](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).

## Fora desta entrega

Sem implantação nova no Cloudflare, sincronização CRM, chatbot, IA ou consulta paga Serpro. O processo de túnel que já estava em execução não foi recriado. Nenhum banco, senha ou credencial foi enviado ao GitHub. O pacote não pretende certificar segurança absoluta nem disponibilidade de serviços externos.

## Repetir QA

Execute no diretório do projeto:

```powershell
python -m unittest discover -s tests -p 'test_*.py'
npm.cmd run test:tools
npm.cmd test --prefix collector
npx.cmd playwright test -c playwright.config.cjs
python tools/db_qa.py
```

Os testes de aplicação e navegador usam bases temporárias. O último comando apenas audita a base real em modo leitura.
