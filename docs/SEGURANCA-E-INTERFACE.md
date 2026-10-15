# Segurança e interface do Radar local

O Radar funcional usa Python/SQLite. Os componentes React são integrados ao mesmo site; mudanças de aparência não exigem migração dos dados dos vendedores.

## Acesso e dados privados

- Sair invalida no servidor todas as sessões da mesma conta. Um cookie copiado antes da saída não permite continuar acessando APIs. Novo login permanece disponível.
- Contatos fictícios/de teste têm proprietário registrado separadamente. Não são compartilhados como os dados oficiais da Receita. A política também alcança listas, CSV, histórico arquivado, BI e agenda, inclusive vínculos antigos.
- A migração preserva os registros existentes e recupera propriedade somente quando existe um único proprietário comercial comprovável. Registros antigos ambíguos são preservados, mas não liberados aos vendedores por adivinhação.
- Sincronização global e monitoramento manual exigem administração, inclusive quando o servidor está em modo local.
- APIs que utilizam JSON exigem objeto na raiz. Conteúdo inválido retorna 400; corpos acima do limite da rota retornam 413. Não há truncamento silencioso do corpo.

## Proteção HTTP

O servidor limita 32 conexões simultâneas. Quando ocupado, retorna 503 com orientação para repetir. APIs autenticadas têm orçamento por conta: 600 leituras e 300 gravações por minuto; o excesso retorna 429. A limitação de tentativas de login permanece separada.

São aceitos os hosts de loopback, o host de `RADAR_PUBLIC_URL`, os hosts adicionais em `RADAR_ALLOWED_HOSTS` e o endereço gravado pelo inicializador em `data/public-url.txt`. Outros hosts são recusados. Não use curingas para abrir essa lista indiscriminadamente.

Essas medidas não substituem firewall, TLS, permissões adequadas do Windows ou backups fora da máquina. Código e aparência carregados pelo navegador continuam visíveis no Inspecionar; proteção real depende das verificações no servidor.

## Ambiente de execução

O inicializador prefere `.venv/Scripts/python.exe` quando disponível. Isso permite atualizar dependências do Radar sem alterar o Python de outros programas. O ambiente completo pode ser reproduzido com `requirements-runtime-lock.txt`. O ambiente `.venv` e os dados não entram no Git.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-runtime-lock.txt
```

Não execute reinstalação ou recarga durante um salvamento em andamento. Faça backup SQLite consistente antes de manutenção; não copie apenas o arquivo principal ignorando o WAL. O ensaio de migração deve ocorrer em uma cópia descartável.

## Interface e testes

Inter e a identidade rubi são preservadas. Cabeçalho móvel agrupa ajuda, atualização e saída em Mais ações. O menu fecha por toque externo ou Escape; em telas baixas a barra lateral inteira pode rolar. Estados vazios continuam legíveis, e controles do BI não devem sair do painel.

O CSS de acabamento da entrada é público, assim como os demais assets do login. APIs, administração e arquivos de dados continuam exigindo autenticação. Há regressão específica para evitar o redirecionamento de um CSS para HTML de login.

O redimensionamento de gráficos e colunas é agrupado para o próximo quadro, com proteção contra repetição e descarte. Essa abordagem evita ciclos de escrita dentro da entrega de ResizeObserver. Referência: [MDN — erros de observação](https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver#observation_errors).

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
npm.cmd run test:tools
npm.cmd run build:tools
npm.cmd run build:react
npm.cmd run test:browser
```

O QA utiliza SQLite temporário, separado da porta 8000. A prévia anônima recebe orçamento maior apenas para simular centenas de navegações automatizadas; os testes de segurança exercitam os limites reais. Chromium cobre os fluxos funcionais; Chromium e WebKit cobrem a auditoria visual. Acessibilidade automática, imagens e testes de toque não equivalem a teste em aparelhos físicos ou a certificação integral.

## Fora desta alteração

Não há consulta paga, nova integração de CRM ou migração para Worker/D1 nesta manutenção. O acesso externo solicitado usa Quick Tunnel para a aplicação local: exige computador e processos ativos, e o endereço pode mudar ao reiniciar. O Worker legado continua sem paridade com a aplicação local e não deve ser publicado como substituto. Auditoria do Windows/BitLocker, decisão de criptografia dos backups e configuração de cópia realmente externa continuam sendo verificações operacionais separadas.
