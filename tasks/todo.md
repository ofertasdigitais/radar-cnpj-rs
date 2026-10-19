# Migração Cloudflare — tarefas

- [x] Confirmar conta de destino com o usuário e exclusão autorizada apenas do Radar.
- [x] Conferir vínculos para garantir que o D1 antigo não pertence à Starker.
- [x] Exportar D1 antigo, verificar SHA-256 e segunda cópia; excluir somente o D1 Radar antigo.
- [x] Criar novo D1 Radar e fixar conta/UUID exclusivos no Wrangler.
- [x] Esquema/snapshot: todas as 35 tabelas, ensaio D1 local e carga remota; FK, contagens e propriedade verificadas.
- [x] Acesso/consulta: login real, revogação/replay, papéis, privacidade e filtros verificados. PBKDF2 SHA256/260k existente preservado em implementação compatível com produção.
- [x] Leads/BI: tratamento, agenda, histórico, mensagens, conclusão, valores, períodos, CSV e PDF testados; smoke externo aprovado.
- [x] Admin/FAQ: configuração/revisão/CSRF, contas, ajuda e integridade validados; restrições operacionais de backup Windows/Crawlee/OSM local documentadas.
- [x] Captação: campanhas, recomendações, notificações, qualificação e cron; fontes/SSRF/propriedade testadas com rede controlada. Overpass real depende do serviço público; nenhuma campanha real criada para ensaio.
- [x] Checkpoint: TypeScript/gate e testes atuais/legados aprovados em banco descartável; APIs e interface conferidas com D1 isolado e online.
- [x] Paid existente confirmado pelo proprietário; Worker exclusivo publicado sem mudanças em recursos Starker.
- [x] Virada: backup/segunda cópia, carga completa, contagens/FK/quick_check e smoke vendedor/admin online aprovados. Snapshot de 19/10 confirmou origem logicamente igual à carga.
- [x] Entrega: GitHub main/branch atualizados em 23a1916, URL workers.dev e logins verificados; limitações documentadas. Workflow Receita ativo e execução 39263337796 aprovada. Backup D1 restaurado isoladamente e conteúdo das 35 tabelas conferido.
