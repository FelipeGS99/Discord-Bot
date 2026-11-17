# WR acumulado, recente e no campeão

## Diagnóstico real

A consulta à Riot para `Mochila#bunny` confirmou:

| Escopo | Resultado consultado |
|---|---|
| Solo/Duo acumulado retornado por League-V4 | 196 vitórias / 193 derrotas = **50,3856…%**, exibido como **50,4%** |
| Cinco partidas anteriores | 3 vitórias / 2 derrotas = **60,0%** |
| Yunara entre as 20 partidas consultadas de Solo/Duo | 3 vitórias / 4 derrotas, 7 jogos com Yunara = **42,9%** |

O card antigo calculava WR apenas nas cinco partidas recentes e arredondava para
um inteiro. Cinco jogos produzem taxas em passos de 20 pontos percentuais. Esse
60% não era o WR acumulado da conta, e o rótulo não diferenciava os escopos.
Além disso, o histórico antigo podia reunir filas diferentes.

## Novo comportamento

Por preferência de apresentação, o WR das últimas cinco partidas foi removido
do Live Match. Permanecem o WR acumulado da fila e o WR no campeão; KDA e
K/D/A médios recentes continuam visíveis. O cálculo recente permanece interno
para diagnóstico e compatibilidade, sem exibir esse terceiro WR no card.

- **WR Solo/Duo ou Flex:** usa as contagens oficiais `wins` e `losses` da League-V4
  para a fila correspondente. Não é calculado pela janela de partidas. Em jogos
  não ranqueados, o acumulado de Solo/Duo continua explicitamente identificado
  como Solo/Duo. Não se afirma que seja WR vitalício ou de todas as filas.
- **WR recente (apenas interno, removido do card):** até cinco partidas anteriores válidas da fila atual, calculado
  por `vitórias / jogos × 100`, com V/D e tamanho da amostra. A precisão completa
  é preservada no cálculo; a apresentação usa uma casa decimal.
- **WR no campeão selecionado:** considera somente o campeão do participante,
  na mesma fila, dentro de até 20 partidas consultadas. Mostra V/D, n, janela e
  aviso para amostra pequena. É uma estatística histórica daquele jogador no
  campeão, **não o WR global do campeão nem seu total na temporada**.
- Sem jogos com o campeão na janela, mostra "sem jogos nos N consultados".
  Falha da API mostra "indisponível"; não se inventa 0%. Taxas realmente iguais
  a zero ou 100% continuam sendo valores válidos quando há jogos observados.
- Partida atual, duplicatas, remakes/partidas muito curtas e resultados não
  booleanos não entram na amostra. Ausência de KDA não elimina uma vitória válida
  da contagem de WR; KDA informa sua própria quantidade de jogos disponíveis.
- Vale para ambos os times, respeitando identidades ocultadas: não se consulta
  outro endpoint para revelar quem o jogo não identificou.

A Riot não oferece nesse fluxo um resumo completo de WR por campeão/temporada.
Obter esse total exigiria percorrer e classificar um histórico muito maior ou
uma fonte autorizada que o fornecesse. A janela de 20 evita apresentar uma amostra
pequena como um total de temporada e limita o custo de API.

## Operação e limites

O cliente consulta até 20 IDs da fila usando o filtro oficial `queue` da Match-V5.
O mesmo histórico serve aos cinco recentes, ao campeão, à análise e à coleta de
builds. Não há uma segunda varredura só para o WR no campeão. Os resultados por
partida usam cache de 24 horas; IDs e League-V4 usam cache de dois minutos.
Elo e WR acumulado compartilham a resposta de League-V4 sem duplicar a requisição.

No primeiro enriquecimento, consultar até 20 partidas por participante pode levar
vários minutos, conforme a cota e o número de participantes. O Live Match inicial
é enviado antes dessas consultas, depois editado. Contextos antigos são
recalculados uma vez para remover o WR ambíguo, sem novas notificações duplicadas.

`?loltrack teste` continua fictício e marcado MODO TESTE. Agora demonstra os WRs acumulado e no campeão, com seus denominadores;
o WR das últimas cinco partidas não é exibido.

## Arquivos e testes

- `services/riot_service.py`: filtro de fila, League-V4 agregado, cálculo fracionário
  e filtros de histórico.
- `services/lol_tracker_service.py`: coleta por participante e migração do contexto.
- `services/lol_presentation.py`: rótulos, V/D, denominadores, uma casa decimal e demo.
- `tests/test_lol_win_rates.py`: 19 testes específicos de cálculo, HTTP/cache,
  filas, duplicatas, remakes, dados ausentes, ocultação e limites dos embeds.
- `tests/test_lol_tracker.py`: adaptação dos doubles ao histórico limitado por fila.

A auditoria real foi somente leitura. Não foram enviadas mensagens ao Discord,
alterados dados de produção, publicados commits ou feito deploy.

Validação final: **331 testes aprovados, zero falhas**; Ruff, `git diff --check` e
`pip check` passaram. Inclui 19 testes específicos de WR e o teste de não repetir
consultas ao roster por causa de uma identidade parcialmente ocultada.
