# Auditoria mobile — Radar CNPJ

Data: 09/10/2026. Referência: commit `882aa34`.

## Escopo e preservação

Auditoria somente de leitura da aplicação. Nenhum ajuste no código funcional, banco principal, sincronização, implantação ou GitHub nesta etapa. Diagnósticos executados em servidores de QA com bancos descartáveis, separados do servidor principal na porta 8000. Este documento é o único novo arquivo fora de `tmp/`.

Chromium e WebKit, com toque simulado, em 320×568, 360×640, 390×844, 430×932 e 844×390. Foram observadas oito áreas: leads, empresas, análises, oportunidades, funil, BI, ferramentas e ajuda; além de cabeçalho/menu, login, editor de lead e modelos de mensagem.

As dez execuções do coletor terminaram, mas NÃO equivalem a dez cenários sem falhas: o coletor registra falhas de toque e usa chamadas locais de abertura/fechamento exclusivamente para continuar a inspeção. Não houve validação em aparelho físico nem do teclado virtual real.

## Problemas confirmados

| Prioridade | Problema | Evidência | Correção proposta, ainda não aplicada |
| --- | --- | --- | --- |
| Alta | Menu inacessível em 320 px | Em ambos os motores, o botão Ajuda intercepta o toque no botão de menu. | Reorganizar o cabeçalho móvel; mover ações secundárias para um menu compacto, preservando o alvo do menu principal. |
| Alta | Toque fora do menu não fecha | Falha nas dez combinações. O scrim, que deveria cobrir a tela, tem `position: relative` e mede 12×2 px no fim do documento. | Excluir elementos de posicionamento estrutural das regras genéricas de botões e proteger o posicionamento fixo do scrim. |
| Alta | Navegação praticamente desaparece na horizontal | Em 844×390, a área rolável de navegação mede apenas 27 px, para conteúdo de 829 px. | Adaptar o fluxo vertical da barra lateral à altura útil; evitar rodapé e marca comprimirem toda a navegação. |
| Média | BI corta a ação Segmentos em 320 px | Em ambos os motores, o botão inicia em x=241 e tem largura de 101 px; ultrapassa a tela de 320 px. | Permitir quebra/reorganização do cabeçalho e seletor de cobertura, sem cortar controles. |
| Média | Campos e alvos de toque inconsistentes | Editor contém campos de 14 px; há controles do BI de 35 px de altura e ações de tabela de 28×28 px. | Padronizar campos móveis em 16 px e ampliar alvos de toque conforme o contexto. |

Campos de 14 px representam risco de zoom ao focar no Safari/iPhone; esse comportamento específico não foi comprovado em aparelho físico. Tabelas com rolagem horizontal intencional não foram classificadas como erro apenas por excederem a largura.

## Causas e animações

- `static/visual.css`, regra `button:not(:disabled)` perto da linha 1553: aplica `position: relative` e `overflow: hidden` indiscriminadamente. A especificidade vence `.sidebar-scrim` de `static/style.css`, removendo seu posicionamento fixo.
- A barra lateral reserva blocos fixos e encolhe `.primary-navigation`. Isso funciona em algumas alturas, mas comprime excessivamente o menu em paisagem. A máscara de 14 px nas bordas agrava a legibilidade quando a região tem apenas 27 px.
- `static/visual.css`, bloco `body:not(.loading)` perto da linha 1584: aplica a animação de entrada a vários painéis, partindo de opacidade zero. `load()` em `static/app.js` alterna essa classe global ao atualizar consultas. Pela leitura do código, a animação pode ser reiniciada em painéis que não precisavam animar. É um risco de cintilação; não foi quantificado por captura temporal neste levantamento.
- Movimento reduzido: nenhuma animação em execução foi encontrada no teste correspondente. Essa preferência foi respeitada nos cenários inspecionados.

## Lacunas do QA anterior

Os testes anteriores verificavam principalmente largura total da página. A página pode passar nesse teste mesmo com controles sobrepostos ou cortados dentro de painéis. Os cenários desta auditoria não mostraram transbordamento da raiz nem erros JavaScript não tratados, mas mostraram falhas reais de interação.

Adicionar regressões que falhem explicitamente para: toque no menu em 320 px; fechamento pelo scrim; espaço útil de navegação em paisagem; visibilidade integral do seletor do BI; campos/alvos móveis; repetição de animações após atualização. Executar nos temas claro e escuro, mais validação final em tablet/celular físico, teclado aberto e rotação. O levantamento atual não certifica todos esses cenários adicionais.

## Evidências locais

Coletor: `tmp/mobile-audit.spec.cjs`; configuração: `tmp/mobile-audit.config.cjs`. Resultados por motor/largura e capturas: `tmp/mobile-audit/` (ignorados pelo Git). Exemplos: `chromium-320.json`, `webkit-320.json` e `menu-landscape-confirm.png`.

## Próximo passo

Aplicar um pacote limitado de correções mobile, sem redesenhar as telas nem alterar dados, seguido de regressões com asserções reais de interação. A aplicação desse pacote depende de novo pedido de correção; esta etapa apenas audita.
