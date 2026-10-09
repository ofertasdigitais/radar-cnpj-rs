# Captação gratuita integrada ao Radar

Integração local concluída em 07/10/2026, por autorização do usuário. Sem deploy, serviços pagos, SERPRO ou envio ao CRM.

## Usar

1. Abra o Radar e pressione Ctrl+F5.
2. Entre em **Ferramentas** (`/#ferramentas`) e localize **Captação autônoma · OpenStreetMap + Crawlee**.
3. Clique em **Criar campanha**. Escolha município do RS, categoria e frequência manual ou diária.
4. Habilite o enriquecimento de sites públicos se desejar completar contatos com Crawlee.
5. Salve e clique em **Coletar agora**. Consulte os resultados em **Ver meus contatos**.

Atualização posterior em 07/10/2026: também é possível agendar até três horários por dia e analisar sugestões numa fila privada, com avisos no sino. Veja [Captação assistida](CAPTACAO-ASSISTIDA-20261007.md).

Campanhas diárias exigem o computador e o servidor ligados. Contatos são separados por conta. Não criamos campanhas reais durante a validação da integração.

## Fonte e limites

- Índice público local separado do banco comercial: 25.485 registros por categoria, 497 municípios, dados da fonte até 06/10/2026. Isso não significa que todos tenham telefone ou site.
- Consultas locais não dependem da disponibilidade do Overpass.
- Até 50 estabelecimentos por rodada, 6 rodadas por conta/24h, 30 rodadas globais/24h; administrador pode reduzir limites.
- Crawlee: até 10 sites por rodada, três páginas por site, respeitando robots.txt e bloqueios. Não acessa áreas privadas.
- Não confirma a existência de WhatsApp e não inventa CNPJ, faturamento ou número de funcionários.
- Atualização semanal do índice é opcional e está desligada. Configuração em `/admin`, aba **Captação automática**. Usa download público e espaço em disco, sem assinatura.
- Atualização manual na pasta do projeto: `python tools/update-local-osm.py`.

## Preservação e verificações

Foi feito merge seletivo, sem substituir o projeto pelo piloto e sem copiar seu banco. A conclusão/baixa de leads foi preservada.

- 78 testes Python, quatro testes do coletor e 11 testes de navegador aprovados na cópia de validação.
- Inicialização ensaiada com cópia consistente do banco real: nenhuma mudança nas 31 tabelas.
- Após reiniciar o servidor principal, conteúdo e contagem das 31 tabelas foram comparados por SHA-256 com o backup: idênticos.
- Banco principal: `quick_check=ok`, nenhuma inconsistência de chave estrangeira; 133.043 empresas, 118 leads comerciais, 452 registros de histórico e duas contas preservados.
- API principal confirmou índice pronto, coletor disponível e modo local; bundle manteve `/api/sales-ops/complete`.

## Backup e recuperação

Pasta: `backup-testes/integracao-captacao-20261007-141909/`.

- `radar-pre.sqlite`: backup SQLite consistente anterior à integração.
- `original/`: código anterior e arquivos necessários para recuperação.
- `integrado/`: candidato usado para testes isolados.

O banco não foi restaurado nem substituído na integração. Uma recuperação futura deve priorizar reverter código, preservando o banco corrente. Não restaurar automaticamente o backup de banco: isso descartaria alterações feitas após sua criação. O backup está no mesmo computador, não equivale a cópia externa.
