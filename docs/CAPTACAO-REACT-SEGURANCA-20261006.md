# Radar: captação, React e preparação de segurança

## O que foi entregue localmente

- Entrada reconstruída em React, Inter local, tela inteira, identidade carmesim e animação de radar. Layout validado em 390, 768, 1024 e 1920 px; movimento reduzido respeitado.
- Central de captação integrada em **Ferramentas → Descoberta automática**, também em React. Não é um site separado. As telas existentes continuam funcionando; não foi feita uma reescrita integral do CRM.
- Campanhas privadas por conta, cidade do RS, 25 categorias, coleta sob demanda ou a cada 24 horas, pausa e edição, histórico e rastreabilidade.
- Resultados externos ficam em `prospect_inbox`. Nunca viram registros oficiais da Receita nem alteram etapas, valores ou observações dos leads existentes automaticamente.
- Deduplicação por identificador OSM e contato; repetição de campanha não sobrescreve o trabalho do vendedor. Paginação incremental por identificador avança além dos primeiros 50 estabelecimentos; ao terminar o recorte, o cursor reinicia para atualização.
- Crawlee consulta opcionalmente até dez sites por rodada, com até duas páginas de contato por site. Recolhe contatos explicitamente publicados e links de redes sociais; não acessa os perfis dessas redes nem inventa e-mail, intenção de compra, faturamento ou existência de WhatsApp.
- Copyright na entrada e no rodapé do Radar. A atribuição OpenStreetMap permanece junto dos resultados.

## Como usar

1. Entre no Radar e abra **Ferramentas → Descoberta automática**.
2. Clique em **Criar campanha**, escolha município e categoria.
3. Se desejar, autorize a consulta dos sites comerciais públicos. Essa opção fica desligada por padrão.
4. Escolha coleta sob demanda ou automática. Salve e use **Coletar agora** para uma rodada manual.
5. Acompanhe o histórico; os contatos aparecem automaticamente em **Contatos externos**, onde podem ser tratados individualmente.

O agendamento exige o servidor local ligado. Não houve ativação de campanha, coleta de leads reais para uma conta, envio de mensagens ou contratação de serviço nesta implementação.

## Fontes, limites e viabilidade

O [OpenStreetMap](https://www.openstreetmap.org/copyright) oferece dados de estabelecimentos sob ODbL, com atribuição e obrigações próprias da licença. Não é uma base completa de empresas nem valida automaticamente CNPJ. A publicação de bases derivadas exige observar as regras de compartilhamento da licença; não removemos a proveniência.

Usamos o endpoint fixo `https://overpass.private.coffee/api/interpreter`, listado na [documentação do Overpass](https://wiki.openstreetmap.org/wiki/Overpass_API) como disponível para projetos, com aviso prévio para grande escala. A instância principal `overpass-api.de` orienta uso comercial em servidor próprio/provedor adequado; por isso não é o padrão desta integração. Nenhum endpoint arbitrário pode ser enviado pelo navegador.

Limites locais: 50 objetos por rodada, seis rodadas por conta em 24 horas, 30 globais em 24 horas e apenas uma execução simultânea. Cache público de consultas por 24 horas reduz carga; não contém dados privados de vendedor. Consultas expiram em 40 segundos e respostas ficam limitadas a 4 MB. Dados sem nome ou fora dos filtros de contato podem reduzir a quantidade importada. A coleta não garante cinquenta leads novos por rodada.

O [Crawlee](https://crawlee.dev/js/docs/introduction) foi integrado com BasicCrawler e transporte HTTP protegido, sem navegador headless. A configuração respeita robots.txt e crawl-delay, não contorna bloqueios e nunca carrega credenciais do Radar no processo coletor. Acesso público não elimina obrigações de privacidade e termos do site.

**Verificação externa em 06/10/2026:** a instância principal respondeu HTTP 504; Private.coffee teve timeout em consultas de teste. A integração de transporte do Crawlee retornou HTTP 200 em `example.com`, e os fluxos de extração/robots foram testados com respostas controladas. A coleta real OSM ponta a ponta permanece pendente de disponibilidade do provedor. Não contornamos certificados TLS nem mascaramos essas falhas. Rodadas incompletas não são apresentadas como sucesso.

## Execução e instalação

As dependências foram instaladas e compiladas nesta máquina. Para outra instalação local, na raiz do projeto:

```powershell
npm.cmd ci --ignore-scripts
npm.cmd ci --prefix collector --ignore-scripts
npm.cmd run build:tools
npm.cmd run build:react
```

São usados React/ReactDOM 19.3.0, Crawlee Basic/Core 3.18.2, Cheerio 1.2.0, ipaddr.js 2.5.0 e robots-parser 3.0.1, com arquivos de lock. Os bundles React são de produção, minificados e sem sourcemaps. Bibliotecas do navegador têm avisos de licença em `static/vendor/THIRD-PARTY-LICENSES.txt`; pacotes do coletor mantêm suas próprias licenças na instalação npm. Auditorias npm das dependências de produção da raiz e do coletor: zero vulnerabilidades reportadas nesta data; isso não substitui auditoria de código.

## Segurança: o que muda

O navegador precisa receber HTML, CSS e JavaScript para mostrar a interface: **não é possível impedir Inspecionar nem esconder dados que o usuário está autorizado a visualizar**. Desativar atalhos não fornece segurança. Chaves, sessões e decisões de autorização ficam no servidor.

- Assinatura de sessão não usa mais a senha administrativa ou a constante `local` como fallback. Desenvolvimento usa segredo efêmero; produção exige `RADAR_SESSION_SECRET` de pelo menos 32 caracteres, gerado aleatoriamente e mantido no servidor.
- `RADAR_ENV=production` desativa o bypass de autenticação sem contas, desativa autenticação Basic legada, exige cookies Secure e deixa o cadastro público fechado por padrão. Um listener não-local sem esse modo não inicia.
- Mantidos cookies HttpOnly/SameSite=Strict e senhas com PBKDF2. Acrescentados limite de tentativas, verificação de Origin/Sec-Fetch-Site, limite global de corpo e timeout de leitura.
- CSP sem scripts externos/inline, proteção contra enquadramento, política de permissões e HSTS em produção. Estilos inline continuam necessários nos gráficos existentes. Não liberamos `unsafe-eval`.
- Arquivos ocultos, fontes de servidor e sourcemaps não são servidos. O banner HTTP não divulga a versão Python.
- Disparo de sincronização RF/Serpro restrito ao administrador em produção. Credenciais Serpro não foram criadas nem testadas; não há confirmação de integração Serpro ativa.
- Coletor bloqueia URLs internas/locais, IPv4 alternativo e IPv6 mapeado, valida todas as respostas DNS e fixa o endereço validado na conexão. Redirecionamentos são limitados ao mesmo host; limite de resposta, timeout, sem cookies e sem passagem de variáveis sensíveis.

O limite de login é em memória, por processo; uma arquitetura distribuída exige controle compartilhado/WAF. O servidor Python local não deve ser exposto diretamente em HTTP público. Secret forte e modo de produção não substituem TLS, backups, controle de acesso e monitoramento.

## Antes de publicar no Cloudflare

**Não publique apenas o conteúdo de `static/` esperando que a captação funcione.** O backend Cloudflare existente ainda não tem paridade com os novos endpoints Python de captação/comercial. É necessária a portabilidade das rotas, tabelas, autorização e agendamento, com testes em D1.

O Crawlee Node não foi empacotado como Worker/Pages Function. Será necessário um coletor separado (máquina/serviço Node com acesso controlado) e comunicação autenticada com o Radar, ou adaptar a coleta a um runtime compatível. Não foi criado serviço externo, conta ou custo novo. Se o coletor continuar neste computador, ele precisa permanecer ligado.

Pendências de lançamento: disponibilidade real do provedor OSM, escolha do runtime do coletor, migração e testes de paridade no Cloudflare, secrets por ambiente, cadastro fechado ou convite, backup/restauração e validação real de isolamento entre contas no ambiente publicado. Não houve deploy em Workers/Pages, push no GitHub nem criação de túnel. A máquina já tinha um Quick Tunnel ativo pelo inicializador interativo; ele foi mantido durante a recarga e, por apontar para este servidor local, também reflete as alterações locais. A recarga passa a adotar esse registro de processo com checagem da porta e do comando, em vez de depender do registro antigo do autostart. Inicializadores com túnel usam modo de produção e cadastro fechado.

## QA e preservação

Testes funcionais e visuais usam SQLite temporário e servidor isolado em 18000; não inicializam API fiscal/Serpro nem alteram leads reais. A migração aditiva foi aplicada numa cópia consistente: empresas, contas, perfis, leads, histórico e configurações permaneceram idênticos; integridade e chaves estrangeiras passaram. Há testes para deduplicação, privacidade de campanha, paginação/cache e falha de rodada sem gravação parcial.

Backup consistente preservado em `data/qa-backups/radar-antes-captacao-react-20261006.sqlite` antes da ativação local. Não usar restauração do backup como limpeza de teste: ela sobrescreveria vendas posteriores. As novas tabelas são aditivas; desativar o agendamento não remove contatos.

Resultado final: 40 testes Python, 5 testes Node de ferramentas, 3 do coletor e 16 Chromium passaram (64 no total). A consulta real de demonstração do Crawlee em example.com concluiu com uma página pública, sem contatos e sem gravação no banco de produção. A disponibilidade externa OSM segue pendente; não foi apresentada como funcionalidade validada ponta a ponta.
