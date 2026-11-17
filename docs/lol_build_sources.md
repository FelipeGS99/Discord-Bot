# LoL: apresentação e builds fundamentadas em observações

## O que mudou

A lista genérica por classe foi removida. Ser um atirador não faz mais o bot
incluir Canhão Fumegante — nem qualquer outro item — no núcleo. Sem evidência
suficiente, o card informa a limitação e não apresenta uma build como validada.

O Live Match mantém fila, horário/tempo relativo, campeão e jogador acompanhado.
Cada participante tem um campo próprio: campeão/Riot ID, elo/LP, WR, KDA, K/D/A
médio, tamanho e período da amostra histórica, maestria e pontos quando disponíveis.
As equipes têm cabeçalhos separados; campos inline se reorganizam no celular.
Identidades omitidas pelo jogo não são resolvidas nem expostas.

No pós-partida, **título, descrição, cor, thumbnail e os sete campos superiores
foram preservados**, incluindo itens finais. Uma fixture da implementação aprovada
verifica essa igualdade. Somente a seção de análise foi reformulada. O aviso de
exclusão do canal continua separado, ao final.

## Fontes investigadas e escolha

| Fonte | Uso nesta entrega | Limitação observada |
|---|---|---|
| [Riot Match-V5](https://developer.riotgames.com/apis#match-v5) | Fonte efetiva de partidas, resultados, composição e timelines de compra. | Amostra local das partidas já consultadas pelo tracker; não é uma amostra global representativa do meta. Depende de chave Riot e cotas. |
| [Riot Data Dragon](https://developer.riotgames.com/docs/lol#data-dragon) | Patch, IDs, nomes, imagens, disponibilidade de itens por mapa e alcance base. | **Não fornece estatísticas nem recomendações de builds.** A versão de assets 16.22.1 corresponde ao patch estatístico 16.22. |
| OP.GG | Investigado como possível fonte externa; não integrado. | A URL de termos consultada retornou 404 e `docs.op.gg` não foi acessível pelo proxy. Não foi estabelecido um endpoint autorizado e estável nesta investigação. Isso não prova que não exista API/parceria. |
| U.GG | Investigado; não integrado. | A resposta à URL consultada não estabeleceu um contrato de API para reutilizar estatísticas de builds. HTTP 200 sozinho não comprova integração autorizada. |
| Lolalytics | Investigado; não integrado. | A rota de termos consultada retornou 404; não foi estabelecido endpoint autorizado e estável. |

Referências consultadas: `https://developer.riotgames.com/docs/lol`,
`https://developer.riotgames.com/policies/general`,
`https://www.op.gg/policies/terms-of-use`, `https://docs.op.gg/`,
`https://u.gg/terms-of-service` e `https://lolalytics.com/terms/`.
Não são consultados endpoints internos desses sites, nem contornados bloqueios.
Uma integração de meta global continua dependendo de um provedor com acesso e
permissão de reutilização de dados; essa integração **não está configurada**.
O sistema entregue funciona com dados oficiais da Riot e explicita sua cobertura.

## Como os dados são obtidos e validados

1. O tracker reaproveita as até 20 partidas anteriores da fila já consultadas por
   participante identificável e o resultado oficial das partidas acompanhadas.
   Não faz crawling adicional de contas para alimentar builds.
2. Compacta observações em `lol_build_samples` no SQLite existente. Registra ID
   da partida/participante, campeão, posição oficial, patch, fila, mapa, horário,
   resultado, inventário final e composição inimiga. **Não grava nomes ou PUUIDs
   nessa tabela estatística.** A chave única evita inflar a amostra ao reencontrar
   a mesma partida em históricos diferentes.
3. Só compara observações do **mesmo campeão, posição, fila, mapa e patch**,
   com no máximo 14 dias e sem datas futuras. Amostras com mais de 30 dias são
   removidas do cache persistente. Assets usam a versão completa mais recente do
   Data Dragon; estatísticas usam o patch major.minor publicado pela Riot.
4. Exige **20 observações** na partição. Se a posição atual não é fornecida por
   Spectator, usa a posição com mais dados como referência e avisa que a rota do
   jogador não foi confirmada; não mistura posições para alcançar o mínimo.
5. Consulta no máximo **oito timelines faltantes por atualização**. A sequência
   vem dos três primeiros itens completos efetivamente comprados, desconsiderando
   compras desfeitas. Venda/troca posterior não reescreve a ordem inicial. Não se
   infere ordem pelos slots do inventário final. O núcleo mais frequente precisa
   aparecer em pelo menos **cinco sequências**.
6. Itens precisam existir, ser compráveis, estar na loja, pertencer ao mapa e
   respeitar restrições de campeão no catálogo atual. Variantes exclusivas de
   Arena não são aceitas para Summoner's Rift. Itens iniciais são compras até
   90 segundos, sem botas/trinkets; botas têm frequência própria.
7. Alternativas precisam de pelo menos **cinco ocorrências**. Os cards mostram
   frequência, vitórias observadas e tamanho do grupo. A frequência de item usa
   inventários finais; a frequência do núcleo usa timelines elegíveis com três
   itens completos. Esses denominadores são diferentes e estão identificados.

Os mínimos são barreiras operacionais, **não prova de significância estatística**.
Mesmo uma build disponível permanece exploratória. Jogos completos/longos são
mais propensos a ter três itens: isso também impede tratar a amostra como meta
ou usar sua taxa de vitória como efeito causal dos itens.

O resultado estatístico fica em cache por cinco minutos; novos dados invalidam o
cache. O Data Dragon é revalidado a cada 30 minutos e mudanças de patch criam uma
nova chave de recomendação. Dados do patch anterior não são misturados. Timelines
usam o cache/cotas/backoff do cliente Riot. Operações SQLite rodam em threads;
falha na coleta ou recomendação não interrompe Live Match, resultados ou os
outros módulos. Se os dados mudam, o bot edita o card de build existente, em vez
de emitir uma notificação duplicada.

## Adaptações e sinergias

Não há conversão de classe em dano exato. Uma lista conservadora de características
de kits identifica algumas ameaças físicas/mágicas/mistas, tanques, armadura,
cura e controle. Campeões não cobertos ficam desconhecidos e a cobertura é
mostrada. Curto alcance usa o alcance base numérico do Data Dragon; transformações,
modificadores e posicionamento real não são inferidos.

Para cada condição atual (por exemplo, três inimigos de curto alcance), o sistema
procura observações com condição semelhante. Só apresenta alternativa condicional
quando há **20 observações condicionais**, ao menos **cinco usos** do item e seu
efeito/tags atuais correspondem à necessidade: redução de cura, penetração,
armadura, resistência mágica ou projéteis em alvos próximos. Se falta cobertura,
informa que não pode justificar uma troca. O núcleo não é substituído por uma
regra fixa de matchup, e uma associação não é apresentada como causalidade.

Para Yunara, há auditoria explícita dos itens 6672 (Mata-Cráquens), 3085 (Runaan),
3031 (Gume), 2512 (Dardos) e 3094 (Canhão), sem atribuir prioridade pelos IDs.
O catálogo atual confirma que Runaan atinge dois inimigos adicionais próximos e
Dardos modifica ataques após a ultimate. São hipóteses de sinergia, não uma regra
absoluta de que um sempre deve substituir o outro.

### Consulta real desta entrega

Foram consultadas cinco partidas recentes de `Mochila#bunny`. Elas continham duas
participações de Yunara no patch 16.22. As presenças nos inventários finais foram:

| Item | Presenças nas 2 observações |
|---|---:|
| Mata-Cráquens | 2 |
| Runaan | 1 |
| Gume do Infinito | 1 |
| Dardos de Caça-Demônios | 1 |
| Canhão Fumegante | 0 |

Uma timeline real também foi lida e interpretada. Esses dados validam consulta,
parsers, IDs e ordem de compras, **não eficiência ou meta de Yunara**. Com duas
observações, o sistema não deve apresentar uma build validada. Os números das
prévias MODO TESTE são fictícios e não são derivados dessa pequena amostra.

## Análise de desempenho

A seção `ANÁLISE DE DESEMPENHO` separa indicadores, comparação e leitura:

- Participação: **(kills + assists) / abates da equipe × 100**. Usa o objetivo de
  abates da equipe ou soma dos cinco colegas completos. Denominador zero,
  dados incompletos ou participação inconsistente geram indisponibilidade.
- CS/min, parcela do dano da equipe quando calculável e visão/min para suporte.
- Comparação prefere mesmo campeão e posição com pelo menos três partidas na
  mesma fila/mapa; depois mesmo campeão; só então histórico mais geral, rotulado.
  Partidas duplicadas/remakes e campos ausentes não inflam o histórico.
- `↑`, `↓` e `≈` usam margens descritivas (10% e tolerâncias absolutas por métrica),
  não testes de significância. Com menos de três jogos comparáveis, não há
  classificação categórica. A leitura não repete simplesmente os números do topo.
- Contextos antigos sem observações completas podem mostrar KDA histórico geral,
  explicitando que fila/posição não foram verificadas.

## Interface, Components V2 e validação visual

O discord.py **2.7.1** instalado oferece `LayoutView` e `Container` (Components V2).
Foram mantidos embeds: edição das mensagens e recuperação de entregas dependem
dos footers/marcadores existentes, e migrar o payload exigiria alterar esses fluxos
já funcionais. A reorganização usa cabeçalhos, campos inline, ícones moderados,
thumbs oficiais e seções com rótulos claros sem introduzir views persistentes.

Prévias HTML/PNG das três mensagens foram renderizadas em Chromium com larguras
1440 e 390 pixels. Verificou-se ausência de overflow horizontal e carregamento de
todas as imagens. São aproximações responsivas, **não captura do cliente Discord**.
A conferência nativa continua disponível com `?loltrack teste`: três mensagens
MODO TESTE no canal privado de demonstração para LOL, nunca disparadas
automaticamente em canais de produção por esta entrega.

## Arquivos desta revisão

Criados: `services/lol_builds.py`, `services/lol_analysis.py`,
`tests/test_lol_build_data.py`, `tests/fixtures/lol_post_approved.json` e este documento.
Modificados: `services/lol_presentation.py`, `services/lol_tracker_service.py`,
`services/lol_tracker_repository.py`, `services/riot_service.py`,
`tests/test_lol_tracker.py`, `tests/fixtures/lol_catalog.json` e `docs/lol_tracker.md`.
Nenhuma dependência de aplicação foi acrescentada.

## Resultado dos testes

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests`:
**311 aprovados, zero falhas** na revisão visual inicial. Inclui 43 novos testes de dados/visuais,
timeline e isolamento de falhas, além dos testes existentes ajustados ao novo
comportamento. Ruff nos arquivos alterados, `git diff --check` e `pip check`
passaram. Não foram adicionadas dependências de aplicação.

As três mensagens de demonstração somaram 2.733, 2.942 e 1.318 caracteres de
embeds, abaixo do limite agregado de 6.000 por mensagem. A verificação em Chromium
confirmou três mensagens, seis imagens PNG e nenhum overflow horizontal nas
larguras 1440 e 390. Nenhuma mensagem foi enviada ao Discord, nenhum canal real
foi criado/apagado e não houve publicação no GitHub ou deploy na Square Cloud.

O ajuste posterior de WR acumulado/recente/campeão é descrito em `docs/lol_win_rates.md`.
