# Auditoria dos 34 canais — 16/11/2026

> Atualização de política: prazos de verificação agora geram avisos e mantêm
> os 33 jogadores/34 canais. Referências abaixo a exclusão automática por
> vencimento descrevem o comportamento anterior. Veja a
> [regra atual de status competitivo e revisão](pro_lives.md#validade-e-status-competitivo).

**33 jogadores / 34 canais tecnicamente monitoráveis no momento da auditoria**:
20 SOOP, nove Huya e cinco Bilibili. Todos tiveram estado **offline válido**
reconhecido. As fichas individuais e os elencos oficiais consultados mantêm os
33 jogadores na primeira divisão da LCK/LPL e nas posições cadastradas.

Não foram encontradas duplicações de sala, titular por plataforma ou identidade
competitiva. As duas contas de knight são de plataformas diferentes, uma
associação intencional. O catálogo foi **preservado byte a byte**, incluindo
fontes, datas, equipes e todos os canais. Ressalvas estão discriminadas aqui e
nas [evidências estruturadas](pro_lives_audit_evidence.json).

O total depende dos prazos existentes: **Flandre e Viper permanecem válidos
somente até 17/11/2026 às 00:00 UTC (16/11 às 21:00 de Brasília)**. Sem nova
validação, o carregador passa automaticamente a **31 jogadores / 32 canais**.
Essa exclusão por prazo foi testada. Não houve renovação automática de validade.

## Flandre e Viper

| Jogador | Vínculo consultado | Canal e titular | Resultado | Pendência |
| --- | --- | --- | --- | --- |
| Flandre | BLG / LPL, TOP; ficha oficial 100, ativo também na lista BLG | Huya [913004](https://www.huya.com/913004); UID 1755405074, Flandre圣枪哥 | Identidade preservada e offline válido | A página informa início antigo em fevereiro/2026. Uso recente e renovação contratual não confirmados; prazo curto preservado. |
| Viper | BLG / LPL, ADC; ficha oficial 193, ativo também na lista BLG | Bilibili [1880715130](https://live.bilibili.com/1880715130); perfil 3690988432263598, BLG_Viper | UID, sala canônica, certificação de jogador BLG e offline válidos | Não foi observada live do próprio Viper nem confirmada renovação; prazo curto preservado. |

Fontes de elenco consultadas novamente:
[ficha Flandre](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER100_INFO.js),
[ficha Viper](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER193_INFO.js) e
[elenco BLG](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM57_INFO.js).
As fichas informavam `UserStatus=1`, `iStatus=1`, `TeamId=57` e posições
`GamePlace=1`/`3`. A lista ativa também inclui Bin; reservas/rotação Tier 1
confirmados são elegíveis, e não se infere Academy pela existência de dois TOP.

As fichas foram exportadas pelo serviço em 17/11 às 01:00 no horário do
serviço (16/11 às 17:00 UTC). O campo interno `sUpdated` é de 25/10 e o arquivo
de equipe informa atualização em 31/10. A consulta atual confirma o que essas
fontes publicam, sem garantir atualização imediata de toda mudança contratual.

A página do GCD da Riot retornou um shell sem tabela legível, os anúncios
Weibo retornaram uma página de visitantes e Leaguepedia retornou HTTP 402.
Trechos indexados sobre vencimento em 17/11 não substituem confirmação primária
de renovação. Por isso, o vínculo publicado foi preservado dentro do prazo já
existente, sem projetá-lo além do corte. Viper mantém `Official.type=0` no cartão
público Bilibili; seu endpoint legado usa um marcador diferente, insuficiente
sozinho para invalidar a certificação atual.

## Bilibili: o que foi realmente validado

| Jogador | Sala canônica | UID do titular | Estado externo | Online do próprio jogador |
| --- | --- | --- | --- | --- |
| knight | [31934797](https://live.bilibili.com/31934797) | 3546597304568306 | Offline válido, conferido novamente após a correção | Não observado |
| Bin | [13914640](https://live.bilibili.com/13914640) | 325315550 | Offline válido, conferido novamente após a correção | Não observado |
| Viper | [1880715130](https://live.bilibili.com/1880715130) | 3690988432263598 | Offline válido, conferido novamente após a correção | Não observado |
| Xun | [26808302](https://live.bilibili.com/26808302) | 594325484 | Offline válido, conferido novamente após a correção | Não observado |
| ON | [26808227](https://live.bilibili.com/26808227) | 398692774 | Offline válido, conferido novamente após a correção | Não observado |

Nas cinco salas, o UID de `get_info`, o perfil público, `get_anchor_in_room` e a
resolução perfil→sala de `getRoomInfoOld` coincidem. Os IDs do catálogo são salas,
não IDs de perfil. Os cinco perfis apresentam identificação oficial de jogador
BLG. `live_status=0` identifica offline, `1` online e `2` replay, sem alerta.

Para validar **online real**, foi consultada a sala pública
[5067](https://live.bilibili.com/5067), descoberta no diretório público
`xlive/web-interface/v1/webMain/getList`. `get_info` retornou `code=0`, sala
canônica 5067, `live_status=1`, título e início `2026-11-16 21:36:05` no formato
local da plataforma. O adaptador real reconheceu a mesma sessão em consultas
independentes. Em uma checagem posterior, a sala retornou `live_status=2`
(replay), corretamente reconhecido como ausência de transmissão ao vivo,
sem notificação. Após a correção, outro controle público, a sala
[1713545054](https://live.bilibili.com/1713545054), teve estado online, horário
válido e título reconhecidos pelo adaptador. Os controles **não são jogadores
do catálogo** e não foram cadastrados.

Assim, o protocolo online e offline foi validado externamente. **Não foi
observado cada um dos cinco jogadores iniciando/encerrando uma transmissão.**
As transições de cada sala, notificações pendentes e deduplicação foram
validadas por simulação automatizada, claramente separada das capturas reais.
Não se afirma validação natural de ponta a ponta por jogador.

### Erros e correção limitada ao parser Bilibili

O transporte já rejeitava HTTP diferente de 200 antes de entregar dados ao
parser. A auditoria confirmou que HTTP 403, 404, 412, 429, 500 e 503, mesmo com
corpo JSON que pareça offline, geram erro e não atualizam o último estado válido.
HTML de desafio, código de aplicação -412/-352 e sala divergente também são
inconclusivos, nunca offline. Uma tentativa de diretório retornou **HTTP 200 /
code=-352**; ela não foi usada como estado, e outro diretório público forneceu
o controle online. As cinco consultas de status não tiveram esse erro.

Foram reproduzidas duas lacunas do parser anterior em testes: `code=false` era
aceito como zero, e `live_time` arbitrário ou nulo podia gerar uma sessão falsa.
A correção exige envelope e sala com estrutura válida, código inteiro zero,
horário de início no formato esperado e data válida, além de título textual.
Respostas malformadas geram `PlatformError`. O horário é preservado como ID de
sessão, sem mudar fuso ou regras de notificação. Nenhum outro adaptador mudou.

## Auditoria completa por canal

Todas as linhas têm vínculo competitivo conferido por ficha individual e lista
ativa da equipe, titularidade compatível com as fontes preservadas e consulta
de estado válida. A marca “histórico” sinaliza uma limitação de uso recente,
sem inventar mudança de conta ou ausência de vínculo competitivo.

| Jogador | Equipe / liga | Posição | Plataforma / canal | Estado | Ressalva |
| --- | --- | --- | --- | --- | --- |
| Flandre | Bilibili Gaming / LPL | TOP | huya [913004](https://www.huya.com/913004) | Offline válido | Início reportado 2026-02-09; revisão antes de 17/11 00:00 UTC |
| Jiejie | EDward Gaming / LPL | JUNGLE | huya [913005](https://www.huya.com/913005) | Offline válido | Histórico: início reportado 2024-02-17 |
| knight | Bilibili Gaming / LPL | MID | huya [969689](https://www.huya.com/969689) | Offline válido | Histórico: início reportado 2023-07-03 |
| knight | Bilibili Gaming / LPL | MID | bilibili [31934797](https://live.bilibili.com/31934797) | Offline válido | Online individual não observado |
| JackeyLove | Top Esports / LPL | ADC | huya [111800](https://www.huya.com/111800) | Offline válido | Nenhuma inconsistência encontrada |
| Meiko | Invictus Gaming / LPL | SUPPORT | huya [913001](https://www.huya.com/913001) | Offline válido | Nenhuma inconsistência encontrada |
| TheShy | Invictus Gaming / LPL | TOP | huya [991111](https://www.huya.com/991111) | Offline válido | Nenhuma inconsistência encontrada |
| Kiin | Gen.G / LCK | TOP | soop [rldls5656](https://play.sooplive.com/rldls5656) | Offline válido | Nenhuma inconsistência encontrada |
| Canyon | Gen.G / LCK | JUNGLE | soop [rjsqn0618](https://play.sooplive.com/rjsqn0618) | Offline válido | Nenhuma inconsistência encontrada |
| Chovy | Gen.G / LCK | MID | soop [wlgnsdl0303](https://play.sooplive.com/wlgnsdl0303) | Offline válido | Nenhuma inconsistência encontrada |
| Duro | Gen.G / LCK | SUPPORT | soop [jmg3495](https://play.sooplive.com/jmg3495) | Offline válido | Nenhuma inconsistência encontrada |
| Peyz | T1 / LCK | ADC | soop [rlantnghks](https://play.sooplive.com/rlantnghks) | Offline válido | Nenhuma inconsistência encontrada |
| Faker | T1 / LCK | MID | soop [leesh2148](https://play.sooplive.com/leesh2148) | Offline válido | Nenhuma inconsistência encontrada |
| Siwoo | Dplus KIA / LCK | TOP | soop [siwoojun1234](https://play.sooplive.com/siwoojun1234) | Offline válido | Nenhuma inconsistência encontrada |
| Doran | T1 / LCK | TOP | soop [choi15778](https://play.sooplive.com/choi15778) | Offline válido | Nenhuma inconsistência encontrada |
| PerfecT | KT Rolster / LCK | TOP | soop [nsmin1243](https://play.sooplive.com/nsmin1243) | Offline válido | Nenhuma inconsistência encontrada |
| Lucid | Dplus KIA / LCK | JUNGLE | soop [tagada008](https://play.sooplive.com/tagada008) | Offline válido | Nenhuma inconsistência encontrada |
| Oner | T1 / LCK | JUNGLE | soop [ansguswns519](https://play.sooplive.com/ansguswns519) | Offline válido | Nenhuma inconsistência encontrada |
| Cuzz | KT Rolster / LCK | JUNGLE | soop [yhk7737](https://play.sooplive.com/yhk7737) | Offline válido | Nenhuma inconsistência encontrada |
| Raptor | BNK FearX / LCK | JUNGLE | soop [jun25jin](https://play.sooplive.com/jun25jin) | Offline válido | Nenhuma inconsistência encontrada |
| ShowMaker | Dplus KIA / LCK | MID | soop [showmakerr](https://play.sooplive.com/showmakerr) | Offline válido | Nenhuma inconsistência encontrada |
| Bdd | KT Rolster / LCK | MID | soop [s735258](https://play.sooplive.com/s735258) | Offline válido | Nenhuma inconsistência encontrada |
| Smash | Dplus KIA / LCK | ADC | soop [tlsrmawo](https://play.sooplive.com/tlsrmawo) | Offline válido | Nenhuma inconsistência encontrada |
| Ruler | Gen.G / LCK | ADC | soop [pwh9811](https://play.sooplive.com/pwh9811) | Offline válido | Nenhuma inconsistência encontrada |
| Career | Dplus KIA / LCK | SUPPORT | soop [pro20040829](https://play.sooplive.com/pro20040829) | Offline válido | Nenhuma inconsistência encontrada |
| Keria | T1 / LCK | SUPPORT | soop [fbalstjr1234](https://play.sooplive.com/fbalstjr1234) | Offline válido | Nenhuma inconsistência encontrada |
| Effort | KT Rolster / LCK | SUPPORT | soop [dltkdgh2000](https://play.sooplive.com/dltkdgh2000) | Offline válido | Nenhuma inconsistência encontrada |
| 369 | Top Esports / LPL | TOP | huya [520369](https://www.huya.com/520369) | Offline válido | Histórico: início reportado 2023-10-10 |
| Breathe | Anyone's Legend / LPL | TOP | huya [390001](https://www.huya.com/390001) | Offline válido | Nenhuma inconsistência encontrada |
| Tian | Top Esports / LPL | JUNGLE | huya [594877](https://www.huya.com/594877) | Offline válido | Nenhuma inconsistência encontrada |
| Bin | Bilibili Gaming / LPL | TOP | bilibili [13914640](https://live.bilibili.com/13914640) | Offline válido | Online individual não observado |
| Viper | Bilibili Gaming / LPL | ADC | bilibili [1880715130](https://live.bilibili.com/1880715130) | Offline válido | Revisão antes de 17/11 00:00 UTC; Online individual não observado |
| Xun | Bilibili Gaming / LPL | JUNGLE | bilibili [26808302](https://live.bilibili.com/26808302) | Offline válido | Online individual não observado |
| ON | Bilibili Gaming / LPL | SUPPORT | bilibili [26808227](https://live.bilibili.com/26808227) | Offline válido | Online individual não observado |

### Contas históricas

O `startTime` reportado pela Huya aponta 2023 para knight e 369, 2024 para
Jiejie e fevereiro/2026 para Flandre. São **valores do campo da página**, não
um histórico exaustivo de transmissões. Não demonstram abandono, exclusividade
ou uso recente. As identidades continuam compatíveis com as associações
publicadas. Foram mantidas e sinalizadas para revisão humana de uso atual.
Os apelidos `JDG.knight` e `JDG.369` são antigos; equipe atual veio das fichas e
dos elencos oficiais, não desses apelidos. knight também possui a conta Bilibili
confirmada; os dois canais não são deduplicados entre plataformas.

### Escopo e integridade

Foram reconsultadas **33 fichas individuais e dez arquivos de equipe**; todas
as verificações de identidade, equipe, posição e lista ativa passaram. Dois
endpoints Tencent tiveram HTTP 503 transitório; foram refeitos após espera,
sem concluir inatividade por erro de rede. A evidência preserva URLs, datas de
consulta, data de exportação e `sUpdated`, distinguindo esses campos.

Foram conferidos todos os registros, inclusive fora do carregador, para evitar
que um prazo vencido escondesse uma duplicação. Nenhum canal ou proprietário
por plataforma aparece vinculado a jogadores diferentes. Não foi encontrado
jogador fora das duas ligas/primeira divisão nas fontes consultadas. Todas as
posições seguem cobertas. Não houve inclusão de novos jogadores ou canais.

## Testes e limites operacionais

- **122 testes existentes passaram antes da correção.**
- **130 testes passaram após a correção**, incluindo oito novos testes Bilibili:
  capturas reais online/offline/replay, salas divergentes, estrutura inválida,
  HTTP de erro com corpo aparentemente offline, HTTP 200 com erro/desafio e
  transições das cinco salas por HTTP local → monitor → SQLite.
- O teste das cinco salas confirma cinco alertas pendentes na transição
  simulada, ausência de repetição após confirmação e recriação do repositório,
  preservação do estado online durante falha HTTP 412 e encerramento válido.
  O Discord é simulado na suíte; não houve envio de mensagem real.
- O carregador real aceitou 33 jogadores/34 contas. Após o prazo de Flandre e
  Viper, aceitou 31/32 no teste de tempo futuro. O catálogo não mudou, e os
  único arquivo Python existente alterado foi `services/pro_live_platforms.py`,
  somente na função `parse_bilibili`.
- `git diff --check` passou. Consultas usaram HTTP assíncrono, timeouts e limites
  existentes. Não houve navegador automatizado, acesso ao token Discord,
  alteração de banco de produção, publicação no GitHub ou deploy Square Cloud.

A aptidão indicada é técnica e condicionada a dados válidos, rede disponível e
canal de notificações configurado. Endpoints das plataformas podem mudar ou
bloquear consultas; falhas continuam desconhecidas e preservam o último estado.
As ressalvas de contrato e uso de contas históricas não foram escondidas no
total. Não foi observada uma transição natural de live de jogador neste teste.
