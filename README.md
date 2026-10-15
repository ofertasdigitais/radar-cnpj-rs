# Radar CNPJ RS

Estado atual e limites da implantação: [situação em 14/10/2026](docs/STATUS-20261014.md).

Aplicação web para consultar empresas abertas recentemente no Rio Grande do Sul, com filtros por período, CNAE, segmento, município, região, situação cadastral e MEI.

## Estado desta versão — 09/10/2026

A versão funcional é **Python/SQLite local**, com componentes React integrados,
Painel de Leads, BI comercial, PDF personalizado, captação, `/admin` e Central
de Ajuda. O código pode ser versionado sem migrar nem substituir o banco.
CRM/Base44 fica para outra versão e **não possui sincronização ativa**; sua
estrutura foi preservada por enquanto. Cloudflare está em espera: o Worker
legado não tem paridade com todas as funções atuais. Não publique essa pasta
nem execute migrações remotas antes de fechar os bloqueios documentados.

- [Validações e limites desta entrega](docs/ENTREGA-QA-20261009.md)
- [Segurança, interface e ambiente isolado](docs/SEGURANCA-E-INTERFACE.md)
- [Auditoria, correções e preparação de migração](docs/AUDITORIA-RADAR-20261007.md)
- [Administração e parâmetros](docs/ADMIN-20261007.md)
- [Central de Ajuda](docs/AJUDA-E-QUALIFICACAO-20261007.md)

**GitHub guarda o código, não o banco nem um backup dos vendedores.** `data/`,
backups, `.env`, credenciais, arquivos SQLite e logs ficam fora do Git.

## Recursos da interface

- painel executivo com indicadores de volume, MEIs, alcance territorial e contatos públicos;
- evolução mensal, ranking de segmentos e municípios em destaque;
- períodos rápidos de 7, 30, 90 e 365 dias;
- filtros avançados combináveis e pesquisa por empresa ou CNPJ;
- ficha completa da empresa em painel lateral;
- score de acionabilidade calculado por recência e disponibilidade de contato;
- área de leads de alto potencial com índice, recência, contato e atalho para a ficha;
- perfis de prospecção persistentes, incluindo criação de filtros salvos;
- CNAE exibido com código e descrição oficial da tabela CNAE da Receita;
- funil comercial com etapas de novo lead até convertido;
- favoritos, anotações e Painel de Leads privado por conta, persistidos no banco local;
- filtros por etapa do lead e favoritos;
- sincronização direta com as tabelas oficiais da Receita Federal;
- exportação CSV;
- layout responsivo para computador, tablet e celular.

## Persistência para a equipe

Os dados ficam no SQLite em `data/radar.db`. Isso inclui os registros trazidos
da Receita, perfis de prospecção, leads selecionados em cada painel, etapa do
funil, favoritos e anotações do vendedor. As ações feitas pela equipe não ficam presas ao navegador: são
gravadas no servidor e continuam disponíveis para o próximo acesso.

O navegador guarda apenas preferências de apresentação, como tema e perfil
selecionado. Para hospedar na sua máquina, mantenha a pasta `data` junto do
programa e não execute uma segunda cópia usando o mesmo arquivo. Faça cópias
de segurança do arquivo `data/radar.db` antes de atualizações importantes.

Na configuração de nuvem deste projeto, o `render.yaml` monta o banco em
`/var/data`, um disco persistente. Sem um volume persistente, qualquer banco
local da nuvem pode ser apagado quando o serviço for recriado.

## Executar

Requer Python 3.10 ou superior e as dependências de `requirements.txt`.
Os arquivos compilados da interface já ficam em `static/`.

```powershell
python -m pip install -r requirements.txt
# Para o importador OSM local e o QA completo, instale também:
python -m pip install -r requirements-capture.txt
# Em instalação nova, configure credenciais e segredo conforme .env.example.
python app.py
```

Abra `http://localhost:8000`. Na primeira execução, a sincronização oficial é iniciada em segundo plano e a interface mostra seu progresso. Os registros aparecem após o cruzamento final; dados fictícios ficam desativados por padrão.

### Iniciar automaticamente no Windows

Depois de executar `INICIAR RADAR.cmd` uma vez e criar o acesso administrativo,
use `INSTALAR RADAR AUTOMATICO.cmd`. O Windows passará a iniciar o servidor em
segundo plano quando este usuário entrar no sistema, sem exigir que uma janela
fique aberta. O estado e os logs ficam na pasta `data`; `PARAR RADAR AUTOMATICO.cmd`
encerra a execução registrada.

Para iniciar também um túnel Cloudflare temporário, use
`INSTALAR RADAR CLOUDFLARE AUTOMATICO.cmd`. O endereço será gravado em
`data/public-url.txt` e pode mudar quando o computador ou o túnel for reiniciado.
Para um endereço fixo, use um túnel nomeado na conta Cloudflare ou publique o
serviço em uma nuvem com volume persistente.

## Hospedagem futura (não ativada nesta entrega)

As instruções abaixo são referências históricas. Render com disco persistente
é pago; não é a opção gratuita solicitada. Para Cloudflare, consulte primeiro os
bloqueios da auditoria. Subir código ao GitHub não autoriza publicar serviços.

O projeto inclui `Dockerfile` e `render.yaml` para publicação como serviço web com disco persistente. No Render:

1. coloque este projeto em um repositório Git;
2. crie um Blueprint usando o `render.yaml`;
3. informe `RADAR_ADMIN_USER` e `RADAR_ADMIN_PASSWORD` quando solicitado;
4. aguarde o primeiro deploy e a primeira sincronização oficial.

A configuração provisiona um serviço web, volume persistente de 30 GB, health check, autenticação e sincronização automática. A aplicação usa a porta fornecida pela nuvem e escuta em `0.0.0.0`.

O mesmo site pode ser instalado no celular ou computador como PWA pelo menu do navegador. Não é necessário manter versões desktop e mobile separadas.

Para testar autenticação localmente, configure as variáveis de `.env.example`
no ambiente e substitua a senha de exemplo e o segredo. Em produção, o servidor
exige administrador e segredo válido; não reutilize credenciais de testes.
Somente desenvolvimento isolado pode operar sem autenticação. O arquivo `.env`
não é carregado automaticamente pelo Python. Na instalação Windows existente,
use os iniciadores para preservar as credenciais protegidas e o banco.

## Repetir QA sem tocar a base funcional

```powershell
python -m pip install -r requirements.txt -r requirements-capture.txt
python -m unittest discover -s tests -q
npm ci
npm run build:react
npm run test:tools
npx playwright install chromium
npm run test:browser
```

Testes de navegador usam bases temporárias nas portas 18000/18001, sem iniciar
cargas da Receita ou coletores externos. Não devem apontar para a porta 8000.
Na instalação já ligada, `python tools/qa_live_readonly.py` confere as rotas
de Admin/Ajuda e a integridade em modo somente leitura; autentica com a
credencial Windows existente e retorna erro se alguma verificação falhar.
O workflow `QA local` do GitHub usa somente ambiente descartável, sem deploy,
segredos da operação ou banco real.

## Atualização automática

O programa consulta diretamente o repositório WebDAV dos Dados Abertos do CNPJ, detecta a competência mais recente e cruza automaticamente:

- Estabelecimentos;
- Empresas;
- Simples/MEI;
- Municípios.

Durante o processamento são mantidos somente estabelecimentos do RS abertos nos últimos 120 dias. Os ZIPs são apagados depois de processados; etapas comerciais, favoritos e anotações existentes são preservados.

O catálogo é verificado de hora em hora e uma nova sincronização ocorre somente quando a Receita publicar uma competência diferente da armazenada localmente. Também é possível acompanhar ou iniciar a operação em **Sincronizar Receita**. Para desativar temporariamente a sincronização ao iniciar:

```powershell
$env:RADAR_AUTO_SYNC='0'
python app.py
```

> A Receita publica um snapshot nacional mensal, não um incremento separado por estado. Em agosto de 2026, as tabelas necessárias somam aproximadamente 7,2 GB compactados. A primeira execução pode levar bastante tempo conforme a conexão; as seguintes só ocorrem quando a base precisa ser atualizada.

O identificador já aceita o formato alfanumérico do CNPJ adotado em 2026.

## Monitor diário Serpro

O módulo **Monitor Serpro** pode rodar uma rodada diária automática e também ser executado sob demanda. Ele seleciona os CNPJs recentes ainda não validados, consulta a API oficial e registra o horário, a fonte, a fila, o limite diário, as atualizações e as falhas. O painel não mascara uma ausência de credenciais: enquanto a integração não estiver configurada, mostra exatamente quais dados faltam.

Configure as variáveis no ambiente do servidor (nunca no código ou no navegador):

```powershell
$env:RADAR_SERPRO_ENV='producao' # ou homologacao
$env:RADAR_SERPRO_CONSUMER_KEY='sua-consumer-key'
$env:RADAR_SERPRO_CONSUMER_SECRET='seu-consumer-secret'
$env:RADAR_SERPRO_USER_CPF='cpf-do-usuario-responsavel'
$env:RADAR_SERPRO_DAILY_LIMIT='50'
$env:RADAR_SERPRO_MONITOR_DAYS='30'
$env:RADAR_SERPRO_DAILY_HOUR='6'
```

O feed opcional `RADAR_DISCOVERY_URL` aceita JSON no formato `{"cnpjs":["..."]}` ou uma lista de objetos com a chave `cnpj`. Assim, um provedor incremental pode entregar novos números automaticamente para validação. Sem esse feed, a Serpro revalida CNPJs já conhecidos, mas não inventa uma descoberta em massa.

A contratação da Consulta CNPJ é feita no Serpro e pode envolver cobrança após o período/demonstração. Use `RADAR_SERPRO_DAILY_LIMIT` para controlar o consumo.

## Consulta no mesmo dia

A base aberta em lote é mensal e não oferece um feed público de novos CNPJs. Para acompanhar um CNPJ conhecido logo após sua emissão, a evolução prevista é integrar a API Consulta CNPJ do Serpro e criar uma lista de monitoramento por CNPJ. Essa modalidade consulta diretamente a base da Receita, mas exige contratação, e-CNPJ e credenciais próprias. A descoberta em massa de todos os novos CNPJs do RS no mesmo dia depende de um provedor comercial com feed intradiário ou de um convênio institucional; não pode ser obtida do snapshot aberto mensal.

## Estrutura

- `app.py`: servidor HTTP e API SQLite;
- `importer.py`: regras de normalização, segmento e região reutilizadas pelo sincronizador;
- `syncer.py`: descoberta, download, cruzamento e recorte automático da Receita;
- `static/`: interface web;
- `tests/`: testes do importador e filtros.
