# Central de Ajuda e qualificação · 7 de outubro de 2026

## Uso no Radar

- Entre normalmente e abra **Central de Ajuda**, no menu, ou **Ajuda**, no topo. Endereço: `/#ajuda`; `/ajuda` também encaminha para o módulo.
- Pesquise por dúvida ou escolha uma categoria. O vendedor vê 19 guias iniciais; o administrador também vê dois guias administrativos.
- **Abrir ferramenta** leva à área correta. **Guiar na tela** destaca os controles e explica os passos, sem cadastrar, coletar, enviar mensagem ou alterar leads.
- **Sim / Ainda tenho dúvidas** registra uma avaliação por conta e artigo. O administrador vê somente os totais, não a identidade dos avaliadores.
- A ajuda exige login. Não usa IA paga, chatbot externo ou serviço de busca.

## Manter o FAQ sem código

1. Abra `/admin#help` com uma conta administrativa.
2. Selecione um artigo ou clique em **Novo artigo**.
3. Edite título, resumo, passos (um por linha), categoria, palavras de busca e atalho.
4. Marque **Publicado** para disponibilizar. Desmarque para manter como rascunho. Conteúdo administrativo exige **Somente administradores**.
5. Clique em **Salvar artigo**. Esse botão é independente de **Salvar parâmetros**.

Textos não executam HTML ou scripts. Edições concorrentes geram conflito de revisão, sem sobrescrever silenciosamente o artigo da outra sessão. O início do servidor não substitui artigos editados pelos padrões iniciais.

## Contatos externos → Painel de Leads

1. Abra **Ferramentas → Contatos externos**.
2. Use **Tratar** para registrar dados e situação. O salvamento verifica se outra sessão já alterou o contato.
3. Clique em **Encaminhar ao painel**. Escolha um responsável da própria conta.
4. Informe o CNPJ e clique em **Conferir empresa**. Confira razão social, nome comercial e município.
5. Confirme a correspondência e conclua. CNPJ ausente na base permanece como contato externo; não é fabricado um cadastro da Receita.

Um atendimento novo entra como **Qualificado**, com origem, campanha e persona. Telefone e e-mail externos vão às observações; os dados oficiais não são substituídos. Atendimento existente mantém etapa, valores e observações. Abordagem ativa por outro responsável exige confirmação explícita. Repetir o mesmo encaminhamento não duplica lead ou histórico.

O vínculo e as alterações têm histórico privado. O resumo da prospecção externa é de todos os períodos da conta; não é a mesma base dos indicadores de negociação. O vínculo acompanha o atendimento: se ele for removido do painel, o contato externo permanece e pode ser encaminhado novamente.

## Indicadores com contexto

Em **Painel de Leads → Rotina do vendedor e relatórios → Qualidade**, abra **Como estes números são calculados?**.

- Conversão comercial: Convertidos / todos os leads do recorte de **entrada no painel**.
- Pipeline: valor negociado dos leads ativos. Receita: valores fechados dos Convertidos.
- Médias: somente datas válidas posteriores à entrada; mostra quantidade de amostras. Sem amostra aparece `—`.
- Valores monetários antigos têm zero como padrão. Não é possível reconstruir se era campo vazio ou uma operação legitimamente sem receita. O painel sinaliza Convertidos sem valor positivo, sem inventar valores.
- Etapas são estoque atual, não retenção histórica. Não confundir recorte por entrada com o histórico de modificações por dia no Painel de Leads.

## Backup e recuperação

Em `/admin#system`, crie uma cópia consistente e use **Verificar recuperação**. O teste abre o backup em modo somente leitura, copia para um diretório temporário, confere integridade e relações e compara os registros de cada tabela. A cópia temporária é descartada. **Não restaura nem substitui a produção.**

Foi ensaiado o backup `radar-20261007-083830-8ee6e395.sqlite`: 23 tabelas conferidas, integridade aprovada e zero violações de relações. Preservados 133.043 empresas, 2 contas, 2 perfis, 108 leads e 392 eventos comerciais. Backups têm dados privados; guarde outra cópia fora deste computador. Chaves DPAPI ainda dependem do mesmo usuário Windows e não são portáveis sozinhas.

## Captação: resultado real desta validação

- Crawlee: três testes locais passaram, incluindo extração, bloqueios de rede privada e respeito a robots.txt. São testes controlados, **não uma garantia de coleta em qualquer site**.
- A consulta real de cafeterias em Porto Alegre ao endpoint Overpass configurado expirou após o limite de rede. Até o endpoint de estado expirou. Não foi criado contato, campanha ou sucesso fictício na base operacional.
- Consequentemente, **a captação externa ponta a ponta continua pendente de validação em rede**, mesmo com o coletor instalado. Uma rodada com fonte indisponível aparece como falha, não como zero oportunidades encontrado com sucesso.
- Nenhuma campanha real foi habilitada nesta entrega. Não contorne limites com tentativas repetidas; confira a mensagem e aguarde disponibilidade da fonte.

## Fora desta entrega

Integração/envio ao Base44 e migração/publicação em Cloudflare continuam adiados. Serpro permanece bloqueado. Nenhum serviço pago foi contratado. O túnel que já estava ativo não é uma implantação nova; ele continua apontando para o servidor local.

## Verificação da entrega

- `python -m unittest discover -s tests -p 'test_*.py'`: 51 testes passaram.
- `npx.cmd playwright test -c playwright.config.cjs`: 44 testes passaram, usando bancos temporários.
- Revalidação de Ajuda/Admin após os últimos ajustes: 18 testes passaram, com 390/768/1920 px, ambos os temas e verificações WCAG A/AA por axe.
- `npm.cmd run test:tools`: 5 testes passaram. Coletor Crawlee: 3 testes passaram.
- Antes da ativação, backup adicional consistente: `data/admin-backups/radar-20261007-092041-b4cd7ff0.sqlite`.
- Servidor local recarregado; túnel preexistente preservado. `/api/help` e `/api/admin/help` retornaram 200 para o administrador; acesso anônimo à ajuda retornou 401.
- Após ativar: integridade `ok`, zero violações de relações, 133.043 empresas, 2 contas, 2 perfis, 108 leads, 392 eventos e nenhuma campanha real. Apenas novas tabelas/coluna de suporte e os 21 guias foram inicializados.
- `tools/qa_live_readonly.py` permite repetir as verificações locais sem inicializar a aplicação ou disparar campanhas. A autenticação usa a credencial Windows já existente, sem imprimir senha.
