"""Local, editable help center. Plain text only; no AI or external calls."""
import json
import re
import uuid
from datetime import datetime
import admin_panel

CATEGORIES = {'inicio':'Primeiros passos','empresas':'Empresas e segmentação','leads':'Tratamento de leads',
              'whatsapp':'WhatsApp e telefones','captacao':'Captação e contatos externos',
              'bi':'Métricas e relatórios','problemas':'Resolver problemas','admin':'Administração'}
ACTIONS = {'':'Sem atalho','empresas':'Consultar empresas','segmentar':'Abrir filtros',
           'leads':'Painel de Leads','whatsapp':'Revisar telefone','captacao':'Descoberta automática',
           'contatos':'Contatos externos','csv':'Importar contatos','pesquisa':'Pesquisa e CEP',
           'bi':'BI comercial','pdf':'Relatório personalizado','admin':'Administração'}

def article(key,category,title,summary,steps,action='',tags='',admin_only=False):
    return dict(id=key,category=category,title=title,summary=summary,steps=steps,action=action,
                tags=tags,admin_only=admin_only,published=True)

DEFAULTS = [
 article('comece-aqui','inicio','Como começar a usar o Radar?',
 'Da pesquisa ao acompanhamento: encontre empresas, selecione oportunidades e registre cada avanço.',
 ['Abra Empresas e filtre o perfil de cliente que deseja atender.','Abra a empresa e adicione ao seu Painel de Leads.','No painel, use Tratar lead para registrar etapa, resultado, valores e próxima ação.','Acompanhe os prazos e consulte o BI para entender sua operação.'],'empresas','começar tutorial vendedor rotina'),
 article('contas-privadas','inicio','Meus leads aparecem para outros vendedores?',
 'Cada conta tem seu próprio tratamento comercial. Administradores têm permissões de gestão da equipe.',
 ['Use seu login individual; não compartilhe senha.','Etapas, valores, histórico e mensagens pertencem à conta e ao responsável.','Uma empresa pode ter outro atendimento ativo; o Radar pede confirmação para duplicar a abordagem.','Contatos externos são privados da conta que os captou.'],'leads','conta perfil acesso privacidade'),
 article('segmentar','empresas','Como encontrar um tipo específico de empresa?',
 'Combine categorias comerciais, CNAEs, território e dados de contato para construir seu recorte.',
 ['Abra Empresas e clique em Filtrar.','Pesquise a categoria comercial: restaurante, oficina, clínica ou outro ramo.','Refine por subcategoria, município, período, porte e disponibilidade de contato.','Confira a lista e abra uma empresa antes de incluí-la no painel. CNAE não comprova intenção de compra.'],'segmentar','filtro funil icp segmento subcategoria cnae restaurante indústria'),
 article('colunas','empresas','Como ver mais empresas ou leads lado a lado?',
 'As opções de colunas se ajustam à largura disponível, sem exigir uma grade que corte a tela.',
 ['Escolha Cartões na área de visualização.','Selecione Automático ou uma quantidade de colunas disponível.','Em tablets, teste orientação horizontal. O limite também pode ser definido pelo administrador.','Use Lista quando precisar comparar campos em linhas.'],'leads','tablet colunas cartões lista resolução'),
 article('tratar-lead','leads','Como organizar o tratamento de um lead?',
 'Registre o que aconteceu e, principalmente, qual será o próximo passo.',
 ['Abra Painel de Leads e clique em Tratar lead.','Atualize a etapa comercial e o resultado do contato; são informações diferentes.','Registre próxima ação com data e hora, estratégia e observações.','Informe valores ofertado, negociado e fechado somente quando forem reais.','Salve e confira o histórico e a fila de trabalho.'],'leads','etapa resultado retorno tarefa salvar negociação'),
 article('etapa-resultado','leads','Qual a diferença entre etapa e resultado do contato?',
 'Etapa descreve a oportunidade. Resultado descreve o retorno de uma abordagem.',
 ['Novo e Qualificado organizam a preparação; Contatado indica que a abordagem começou.','Em negociação representa uma oportunidade em discussão; Convertido e Descartado encerram o ciclo.','Não respondeu, Respondeu e Pediu retorno são resultados do contato, não etapas de venda.','Atualize os dois campos conforme a situação real, sem registrar uma venda só porque houve resposta.'],'leads','novo qualificado contatado convertido descartado respondeu'),
 article('atividades-data','leads','Como ver o que fiz em uma data específica?',
 'Use o histórico de atividades para distinguir alterações feitas no dia de leads incluídos no período.',
 ['Abra o Painel de Leads do responsável.','Abra o histórico/atividades e informe a data inicial e final desejadas.','Consulte os eventos e as alterações registradas.','O período comercial do relatório usa a entrada do lead no painel; não é a mesma coisa que data de edição.'],'leads','sexta feira ontem histórico atividade modificação data'),
 article('whatsapp-formato','whatsapp','O número não abre no WhatsApp. O que conferir?',
 'Formato correto não garante uma conta WhatsApp. O Radar não faz verificação automática de existência.',
 ['Abra Revisar telefone e confira DDD e número.','Se houver sugestão de nono dígito, confira antes de usar. Um telefone fixo não deve receber 9 automaticamente.','Teste Abrir WhatsApp; a mensagem ainda depende de você apertar Enviar no aplicativo.','Após conferir, marque Confirmado, Não localizado, Pendente ou Inválido no lead.'],'whatsapp','9 nono dígito inválido não localizado celular ddd'),
 article('mensagens','whatsapp','Como usar modelos de mensagem no WhatsApp?',
 'Modelos preenchem o texto ao abrir a conversa; não disparam mensagens sozinhos.',
 ['No Painel de Leads, clique em Configurar mensagens.','Cadastre os modelos e escolha qual usar no seletor.','Abra o WhatsApp do lead e confira o texto e o destinatário.','Envie manualmente e registre o resultado da abordagem no Radar.'],'leads','mensagem automática modelo apresentação whatsapp enviar'),
 article('campanha','captacao','Como captar contatos sem importar planilhas?',
 'Uma campanha pesquisa estabelecimentos públicos por cidade e categoria no OpenStreetMap.',
 ['Abra Ferramentas → Descoberta automática e clique em Criar campanha.','Escolha nome, município do RS e categoria. Filtros de telefone/site podem reduzir os resultados.','Opcionalmente habilite enriquecimento dos sites públicos.','Salve e clique em Coletar agora, ou escolha frequência diária. O servidor deve estar ligado.','Confira o histórico e abra Contatos externos. A cobertura e a disponibilidade da fonte podem variar.'],'captacao','osm openstreetmap descobrir campanha automático capturar'),
 article('crawlee','captacao','O que o Crawlee completa?',
 'O coletor visita sites comerciais públicos encontrados na campanha, quando você habilita essa opção.',
 ['Habilite enriquecimento de sites ao criar ou editar a campanha.','O coletor procura telefones, e-mails e links publicados de redes sociais.','Ele respeita bloqueios e robots.txt, e não acessa áreas privadas ou perfis sociais.','Não inventa faturamento, funcionários, intenção de compra ou existência de WhatsApp.'],'captacao','crawlee enriquecer site instagram redes sociais email'),
 article('contato-para-lead','captacao','Como levar um contato externo ao Painel de Leads?',
 'Qualifique o contato e vincule um CNPJ existente no Radar, sem criar uma empresa oficial fictícia.',
 ['Abra Contatos externos e clique em Encaminhar ao painel.','Informe o CNPJ correto e escolha um responsável da sua própria conta.','Confira a empresa encontrada e confirme o encaminhamento.','O vínculo preserva o cadastro oficial. Etapa e observações de um atendimento existente não são sobrescritas.','Sem CNPJ localizado, continue tratando o contato externo; ele não entra no BI oficial.'],'contatos','qualificar vincular encaminhar cnpj origem unificar'),
 article('csv-contatos','captacao','Como importar contatos por CSV?',
 'A importação é opcional e serve para fontes próprias, indicações e eventos.',
 ['Abra Importar CSV e baixe o modelo se precisar.','Selecione um arquivo de até 2 MB e 500 linhas.','Mapeie as colunas e revise a prévia; corrija erros antes de confirmar.','Duplicados iguais são preservados. A importação não substitui a base da Receita.'],'csv','csv importar tabela planilha duplicados'),
 article('exportar-crm','leads','Como exportar minha seleção de leads?',
 'Monte um CSV com os campos e os filtros desejados, sem depender de sincronização com CRM.',
 ['No Painel de Leads, abra Exportar CSV.','Escolha nome do arquivo, separador, etapa e situação do WhatsApp.','Selecione as colunas e gere o arquivo.','Confira o mapeamento ao importar no destino. Nesta etapa não há envio automático ao Base44.'],'leads','csv exportar crm campos colunas separador'),
 article('bi-calculos','bi','O que os indicadores comerciais realmente medem?',
 'O BI usa registros do responsável e do recorte selecionados; não estima faturamento da empresa.',
 ['Conversão comercial: quantidade de Convertidos dividida pelos leads incluídos no recorte.','Receita fechada: soma dos valores fechados dos leads Convertidos. Pipeline: valores negociados dos leads ainda ativos.','Prazo de primeiro contato: intervalo entre entrada e primeiro contato registrado. Tempo até fechar considera Convertidos com datas válidas.','Sem datas válidas, uma média fica sem amostra; zero monetário pode significar valor não preenchido. Confira a qualidade dos dados.','Distribuição por etapa mostra o estoque atual, não a passagem histórica entre etapas.'],'bi','conversão fórmula percentual receita pipeline ticket média zero período'),
 article('pdf','bi','Como gerar um PDF com a identidade do Radar?',
 'Personalize título, apresentação, notas e seções antes de baixar.',
 ['No Painel de Leads, abra Rotina do vendedor e relatórios.','Clique em Personalizar relatório PDF. No BI, use Personalizar PDF deste recorte.','Escolha as seções e revise o responsável e o período.','Gere a prévia e baixe. Dados do documento são privados; confira antes de compartilhar.'],'pdf','relatório pdf impressão baixar personalizado'),
 article('sem-resultados','problemas','A campanha não trouxe contatos. E agora?',
 'Uma falha da fonte é diferente de uma coleta concluída sem resultados.',
 ['Confira o estado e a mensagem da última rodada. Falhou não deve ser tratado como sucesso.','Verifique se a campanha está ativa e se o município e a categoria estão corretos.','Filtros obrigatórios de telefone/site podem excluir estabelecimentos. Amplie um critério por vez.','Se a fonte estiver indisponível, aguarde antes de tentar novamente. Não crie campanhas repetidas para contornar limites.'],'captacao','erro timeout falhou indisponível vazio coleta'),
 article('nao-salvou','problemas','Não consegui salvar ou perdi acesso. Como proceder?',
 'Evite repetir uma gravação sem conferir o estado final.',
 ['Leia a mensagem de erro; confira campos obrigatórios e conexão.','Sessão expirada exige entrar novamente. Seu administrador pode ter alterado o acesso.','Após salvar, recarregue a lista ou confira o histórico antes de repetir a ação.','Não restaure um backup para resolver um problema visual. Informe a tela, horário e mensagem ao administrador.'],'leads','salvar sessão erro acesso conexão'),
 article('pesquisa','captacao','Pesquisa e CEP são automáticos?',
 'São consultas auxiliares acionadas pelo vendedor, diferentes das campanhas automáticas.',
 ['Em Pesquisa e CEP, informe empresa e cidade para montar links de pesquisa.','Abra o destino desejado para conferir site, mapa ou presença digital.','Na consulta de CEP, somente o CEP informado é enviado à BrasilAPI.','Resultados podem estar desatualizados e não são gravados automaticamente.'],'pesquisa','cep brasilapi mapa linkedin pesquisar'),
 article('admin-parametros','admin','Como alterar parâmetros sem modificar código?',
 'Use o /admin com a conta administrativa. Parâmetros ficam em rascunho até salvar.',
 ['Abra Administração e escolha a seção.','Altere os parâmetros e revise o contador de pendências.','Clique em Salvar parâmetros e recarregue o Radar para aplicar opções visuais.','Contas e ações de manutenção têm botões próprios. Outra aba pode causar conflito de revisão; atualize antes de tentar novamente.'],'admin','admin parâmetro configuração',True),
 article('backup','admin','Como proteger e testar a recuperação da base?',
 'Backup deve ser consistente, privado e verificável; teste não deve sobrescrever a operação.',
 ['Em Banco e manutenção, crie e baixe uma cópia do SQLite.','Guarde o arquivo fora da pasta pública, com acesso restrito.','Use Verificar recuperação para abrir uma cópia temporária, verificar integridade e comparar os registros.','Um teste bem-sucedido não restaura a produção. Uma recuperação real exige parada planejada e preservação do banco atual.','Chaves Windows DPAPI exigem o mesmo usuário; recadastre-as ao migrar para outro ambiente.'],'admin','backup restaurar recuperação banco sqlite',True),
]

OPERATIONS_GUIDES = [
 article('agenda-retornos','leads','Como usar a agenda e registrar cada contato?',
 'A agenda reúne retornos vencidos, de hoje, próximos dias e leads sem agendamento.',
 ['No Painel de Leads, abra Agenda e retornos e escolha a fila desejada.','Pesquise por empresa, CNPJ ou telefone. A busca percorre toda a agenda, mesmo que só os primeiros resultados estejam na tela.','Clique em Registrar contato, informe o resultado real e, se houver retorno, preencha ação com data e hora.','As notas entram no histórico sem substituir observações anteriores. Abrir WhatsApp não comprova contato.','Se outra sessão alterou a oportunidade, atualize ou reabra a ficha antes de tentar salvar novamente.'],'leads','agenda retorno lembrete tarefa registro contato concorrência'),
 article('nao-contatar','leads','Como impedir novas abordagens a uma empresa?',
 'Não contatar é uma restrição por conta: preserva histórico e valores, mas impede o fluxo de abordagem do Radar.',
 ['Na agenda, clique em Não contatar e registre o motivo.','A empresa sai da agenda e do CSV de leads; o WhatsApp fica indisponível no Radar. O histórico permanece.','O bloqueio vale para os responsáveis desta conta, não para outras contas.','Para retomar, abra Não contatar no fim da agenda e confirme que possui autorização. O Radar não cancela mensagens já enviadas nem contatos feitos fora do sistema.'],'leads','bloqueio consentimento não contatar reautorizar exportação'),
 article('resultados-metas','bi','Como comparar resultados e acompanhar metas?',
 'Entradas usam a inclusão do lead; contatos usam o registro; receita usa a data de fechamento.',
 ['No BI, use Entradas, contatos e fechamentos para escolher o período de resultados.','Compare com o recorte anterior da mesma duração ou use Últimos 7 dias e Este mês.','Troque a métrica do gráfico ou abra Ver evolução em tabela para conferir os valores.','Escolha o mês das metas e salve objetivos de receita, contatos e vendas. As metas são privadas do responsável.','O progresso usa todo o mês escolhido. Fechamentos sem data válida não entram na receita do período. Os dados são operacionais, não um balanço contábil.'],'bi','meta objetivo comparação semana mês receita fechamento datas'),
 article('backup-segunda-copia','admin','Como configurar o backup diário e a segunda cópia?',
 'Backup automático roda com o servidor ligado. A segunda cópia é conferida por hash, sem apagar backups antigos.',
 ['Em /admin → Banco e manutenção, configure Backup automático diário e uma pasta absoluta para a segunda cópia.','Salve os parâmetros e use Criar backup para testar o destino. Confira se a segunda cópia aparece como conferida.','Uma pasta no mesmo computador não protege contra perda do equipamento. Para proteção externa, use pasta sincronizada ou de rede e confira a sincronização separadamente.','Use Verificar recuperação na lista de backups para ensaiar uma restauração em cópia temporária. Nunca publique o banco no GitHub.'],'admin','backup diário automático segunda cópia nuvem sha256 sincronização',True),
]

CAPTURE_GUIDES = [
 article('captacao-horarios','captacao','Como receber recomendações de manhã, à tarde e no fim do dia?',
 'Você configura até três horários por campanha. A busca automática ajuda na descoberta, sem criar leads ativos ou enviar mensagens.',
 ['Abra Ferramentas → Descoberta automática → Criar campanha. Escolha município, categoria e, se desejar, um perfil comercial de referência.','Na frequência, escolha Automática · até 3 horários por dia. O padrão é 08:00, 13:00 e 17:00; ajuste entre um e três horários.','Salve a campanha. Computador e servidor precisam estar ligados; os horários seguem o relógio local do servidor.','Todas as campanhas e consultas manuais compartilham até seis rodadas por conta a cada 24 horas e o limite global. Não é garantia de três rodadas para cada campanha.','Use Pausar para interromper novas coletas. Ao retornar de uma parada, o Radar não dispara todas as rodadas perdidas.'],'captacao','agendamento três horarios manhã tarde automático pausar frequência'),
 article('recomendacoes','captacao','Como analisar recomendações e controlar os avisos?',
 'A fila é privada da sua conta e fica separada dos leads ativos. Correspondência de cidade e categoria não comprova intenção de compra.',
 ['Abra Recomendações pelo sino no topo ou pela Descoberta automática. Há somente um aviso por rodada que encontrou contatos novos.','Na seção Para analisar, confira cidade, campanha, motivo da recomendação e contatos publicados. Selecione individualmente ou marque vários e use Guardar seleção.','Em Selecionadas, clique em Tratar contato para abrir o cadastro externo. Só encaminhe ao Painel de Leads depois de conferir o CNPJ existente na base.','Use Descartar para tirar uma sugestão da fila. Novas coletas do mesmo registro não a sugerem novamente; o contato externo e o histórico são preservados.','No sino, desmarque Receber avisos para silenciar futuras notificações. Isso não pausa campanhas nem apaga recomendações. Avisos são internos ao Radar, não push, e-mail ou WhatsApp.'],'captacao','notificação sino recomendação selecionar descartar analisar interesse captura'),
 article('osm-local','captacao','De onde vêm os contatos e como a base OpenStreetMap é atualizada?',
 'A busca padrão usa um índice público local separado do banco comercial. Crawlee tenta completar os sites informados, sem assinatura paga.',
 ['Na Descoberta automática, confira a data e a disponibilidade da Base OpenStreetMap local. A cobertura depende dos estabelecimentos publicados no mapa.','Filtros de telefone e site exigem esses dados no mapa, antes de consultar sites. Deixe-os desmarcados para ampliar a busca.','A atualização semanal do índice é opcional e administrada em /admin → Captação automática; exige servidor ligado, internet e espaço em disco.','O Crawlee respeita robots.txt e não garante contatos em todos os sites. Não confirma WhatsApp, faturamento, funcionários ou intenção de compra.','Nada encontrado não significa que não existem empresas na região; confira cobertura, filtros e histórico.'],'captacao','openstreetmap osm local geofabrik índice atualização crawlee gratuito'),
]

AUDIT_GUIDES=[
 article('audit-acesso','admin','Como ficam acesso, bloqueios e contas desativadas?',
 'A identidade administrativa do servidor é separada das contas comerciais; nomes iguais não concedem permissões.',
 ['Crie e altere contas em /admin → Contas. Não compartilhe a senha administrativa com vendedores.','Oito tentativas por acesso em 15 minutos geram bloqueio temporário. Usuário e e-mail da mesma conta compartilham esse limite.','Desativar uma conta impede novas sessões e suspende suas coletas. Resultados de uma rodada em andamento não são gravados após a desativação.','Redefinir senha ou permissão revoga sessões. A atualização de segurança pode exigir entrar novamente; os leads não são apagados.','Dados antigos sem responsável não são atribuídos automaticamente por semelhança de nome ou e-mail. Solicite revisão administrativa.'],'admin','segurança conta bloqueio acesso sessão administrador',True),
 article('audit-bi-ativos','bi','Por que um lead concluído sai das prioridades do BI?',
 'Concluído, Convertido e Descartado são estados encerrados, não tarefas pendentes.',
 ['Leads encerrados continuam no histórico e na distribuição por etapa, mas saem dos prazos, maturidade e matriz de ação.','Somente Convertido entra na receita fechada. Concluído sem venda não é faturamento.','Os grupos Vencidos, Hoje a vencer, Próximos 7 dias e Sem prazo não se sobrepõem.','Receita e valores usam centavos registrados, sem inventar estimativas. O recorte por período considera a entrada do lead; não é um relatório de faturamento por data de fechamento.'],'bi','bi concluído conversão ativos receita atraso prazo'),
 article('audit-publicacao','admin','O CRM e a migração Cloudflare já estão conectados?',
 'Não. A estrutura de integração está preparada localmente; publicação e envio continuam desligados.',
 ['CSV continua disponível para importação manual. A ponte Base44 exige receptor, mapeamento de responsáveis e persistência testados.','A configuração de URL e segredo não envia dados. Nunca coloque o segredo no navegador ou em arquivos de exportação.','Antes de publicar o Worker, execute o verificador de prontidão. A versão legada não cobre todos os recursos atuais e a publicação está bloqueada.','Mantenha backup SQLite consistente de todas as tabelas e valide uma restauração isolada. GitHub não é destino para o banco real.','Nenhuma consulta paga Serpro ou serviço de IA foi habilitado. Confirme custos e limites da conta de destino antes de liberar integrações.'],'admin','crm base44 cloudflare migração backup publicação gratuito',True),
]

def ensure_schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS help_articles (
      id TEXT PRIMARY KEY,category TEXT NOT NULL,title TEXT NOT NULL,summary TEXT NOT NULL,
      steps_json TEXT NOT NULL,action TEXT NOT NULL DEFAULT '',tags TEXT NOT NULL DEFAULT '',
      admin_only INTEGER NOT NULL DEFAULT 0,published INTEGER NOT NULL DEFAULT 1,
      revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS help_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS help_feedback (
      article_id TEXT NOT NULL REFERENCES help_articles(id),owner_id TEXT NOT NULL,
      useful INTEGER NOT NULL CHECK(useful IN (0,1)),updated_at TEXT NOT NULL,
      PRIMARY KEY(article_id,owner_id));''')
    if not db.execute("SELECT 1 FROM help_meta WHERE key='seed_v1'").fetchone():
        for item in DEFAULTS:
            db.execute('INSERT OR IGNORE INTO help_articles VALUES(?,?,?,?,?,?,?,?,?,1,?)',
                       (item['id'],item['category'],item['title'],item['summary'],json.dumps(item['steps'],ensure_ascii=False),item['action'],item['tags'],int(item['admin_only']),1,datetime.now().isoformat(timespec='seconds')))
        db.execute("INSERT INTO help_meta VALUES('seed_v1','1')")
    if not db.execute("SELECT 1 FROM help_meta WHERE key='seed_operations_v1'").fetchone():
        for item in OPERATIONS_GUIDES:
            db.execute('INSERT OR IGNORE INTO help_articles VALUES(?,?,?,?,?,?,?,?,?,1,?)',
                       (item['id'],item['category'],item['title'],item['summary'],json.dumps(item['steps'],ensure_ascii=False),item['action'],item['tags'],int(item['admin_only']),1,datetime.now().isoformat(timespec='seconds')))
        db.execute("INSERT INTO help_meta VALUES('seed_operations_v1','1')")
    if not db.execute("SELECT 1 FROM help_meta WHERE key='seed_capture_assist_v1'").fetchone():
        for item in CAPTURE_GUIDES:
            db.execute('INSERT OR IGNORE INTO help_articles VALUES(?,?,?,?,?,?,?,?,?,1,?)',
                       (item['id'],item['category'],item['title'],item['summary'],json.dumps(item['steps'],ensure_ascii=False),item['action'],item['tags'],int(item['admin_only']),1,datetime.now().isoformat(timespec='seconds')))
        db.execute("INSERT INTO help_meta VALUES('seed_capture_assist_v1','1')")
    if not db.execute("SELECT 1 FROM help_meta WHERE key='seed_audit_v1'").fetchone():
        for item in AUDIT_GUIDES:
            db.execute('INSERT OR IGNORE INTO help_articles VALUES(?,?,?,?,?,?,?,?,?,1,?)',
                (item['id'],item['category'],item['title'],item['summary'],json.dumps(item['steps'],ensure_ascii=False),item['action'],item['tags'],int(item['admin_only']),1,datetime.now().isoformat(timespec='seconds')))
        db.execute("INSERT INTO help_meta VALUES('seed_audit_v1','1')")

def listing(db, is_admin=False, edit=False, owner=''):
    where='' if edit and is_admin else ' WHERE published=1'+('' if is_admin else ' AND admin_only=0')
    items=[]
    for row in db.execute('SELECT * FROM help_articles'+where+' ORDER BY category,title COLLATE NOCASE'):
        item=dict(row);item['steps']=json.loads(item.pop('steps_json'));item['published']=bool(item['published']);item['admin_only']=bool(item['admin_only'])
        if edit:
            item['feedback']={str(x[0]):x[1] for x in db.execute('SELECT useful,COUNT(*) FROM help_feedback WHERE article_id=? GROUP BY useful',(item['id'],))}
        else:
            feedback=db.execute('SELECT useful FROM help_feedback WHERE article_id=? AND owner_id=?',(item['id'],owner)).fetchone()
            item['my_feedback']=None if not feedback else bool(feedback[0])
        items.append(item)
    return {'items':items,'categories':{k:v for k,v in CATEGORIES.items() if is_admin or k!='admin'},'actions':ACTIONS if edit else None}

def save(db, actor, raw):
    if not isinstance(raw,dict) or set(raw)-{'id','revision','category','title','summary','steps','action','tags','admin_only','published'}:raise ValueError('Artigo inválido')
    clean={}
    for key,limit in [('title',160),('summary',1600),('tags',300)]:
        value=raw.get(key,'')
        if not isinstance(value,str) or len(value)>limit or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):raise ValueError('Texto inválido: '+key)
        clean[key]=value.strip()
    if not clean['title'] or not clean['summary']:raise ValueError('Preencha título e resumo')
    category=raw.get('category');action=raw.get('action','');steps=raw.get('steps')
    if not isinstance(category,str) or not isinstance(action,str) or category not in CATEGORIES or action not in ACTIONS:raise ValueError('Categoria ou atalho inválido')
    if not isinstance(steps,list) or not 1<=len(steps)<=12 or any(not isinstance(s,str) or not s.strip() or len(s)>1000 for s in steps):raise ValueError('Use de 1 a 12 passos, até 1000 caracteres cada')
    for key in ('admin_only','published'):
        if type(raw.get(key)) is not bool:raise ValueError('Opção inválida: '+key)
    if (category=='admin' or action=='admin') and not raw['admin_only']:raise ValueError('Conteúdo administrativo deve ser restrito ao administrador')
    identifier=raw.get('id') or 'artigo-'+uuid.uuid4().hex[:12]
    if not isinstance(identifier,str) or not re.fullmatch(r'[a-z0-9-]{3,50}',identifier) or type(raw.get('revision')) is not int:raise ValueError('Identificador ou revisão inválida')
    db.execute('BEGIN IMMEDIATE')
    old=db.execute('SELECT revision FROM help_articles WHERE id=?',(identifier,)).fetchone()
    if (old[0] if old else 0)!=raw['revision']:raise LookupError('Artigo alterado por outra sessão. Atualize antes de salvar.')
    revision=(old[0] if old else 0)+1;stamp=datetime.now().isoformat(timespec='seconds')
    db.execute('''INSERT INTO help_articles VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      category=excluded.category,title=excluded.title,summary=excluded.summary,steps_json=excluded.steps_json,
      action=excluded.action,tags=excluded.tags,admin_only=excluded.admin_only,published=excluded.published,
      revision=excluded.revision,updated_at=excluded.updated_at''',
      (identifier,category,clean['title'],clean['summary'],json.dumps([s.strip() for s in steps],ensure_ascii=False),action,clean['tags'],int(raw['admin_only']),int(raw['published']),revision,stamp))
    admin_panel.audit(db,actor,'help.updated','Artigo '+identifier+('; publicado' if raw['published'] else '; rascunho'))
    return {'saved':True,'id':identifier,'revision':revision}
