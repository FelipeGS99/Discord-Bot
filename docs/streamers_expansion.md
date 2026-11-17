# Ampliação do catálogo com Mauro Garih — 16/11/2026

> Atualização de política: prazos de verificação agora geram avisos e mantêm
> os 33 jogadores/34 canais. Referências abaixo a exclusão automática por
> vencimento descrevem o comportamento anterior. Veja a
> [regra atual de status competitivo e revisão](pro_lives.md#validade-e-status-competitivo).

> Esta é a pesquisa de ampliação. Veja também a
> [auditoria posterior dos 34 canais](pro_lives_audit.md), com ressalvas de
> uso de contas históricas, prazos e validação Bilibili online/offline/replay.

Foram acrescentados **23 jogadores Tier 1 e 24 canais**: 16 jogadores SOOP,
três Huya e quatro Bilibili, além de um canal Bilibili para **knight**, já
cadastrado na Huya. O catálogo passou de **10 jogadores/10 canais para
33 jogadores/34 canais**. Os dez cadastros anteriores e seus canais foram
preservados; nenhum código Python foi alterado nesta ampliação.

| Plataforma | Novos jogadores | Novos canais | Total de canais |
| --- | ---: | ---: | ---: |
| SOOP | 16 | 16 | 20 |
| Huya | 3 | 3 | 9 |
| Bilibili | 4 | 5 | 5 |
| CHZZK | 0 | 0 | 0 |
| Douyu | 0 | 0 | 0 |

Os novos jogadores cobrem TOP (6), Jungle (6), MID (3), ADC (4) e Support (4),
independentemente de nacionalidade. Isso ainda representa **cobertura parcial**
das ligas, não uma lista completa de todos os titulares ou suplentes Tier 1.

## Fontes e critérios

A [página indicada](https://www.maurogarih.com/en/herramientas/streamers) e sua
[API pública](https://www.maurogarih.com/api/streamers) foram consultadas via HTTP.
A API informava atualização em **16/11/2026, 16:39:05.163 UTC** e continha 66
entradas: 29 Twitch, 22 SOOP, sete CHZZK, cinco Bilibili e três Huya; nenhuma
Douyu. A página renderizada possuía uma cópia anterior de 14/11; foram comparadas
as associações com a API atual. O rótulo de live desse site não foi usado como
prova de estado.

Para cada cadastro aceito, o vínculo e a posição foram conferidos na ficha
individual e na lista `activePlayers` da equipe publicadas no serviço oficial
Tencent/LoL Esports. As fontes individuais estão na tabela e todas as URLs de
elenco e canal constam do [catálogo](../pro_lives_roster.json). `UserStatus=1`,
`iStatus=1`, equipe e posição foram comparados. O mapeamento oficial
[GamePlace](https://lpl.qq.com/web201612/js/public.js) é 1=TOP, 2=MID, 3=ADC,
4=Support, 5=Jungle. A data de exportação desses dados não é uma data de
transferência. A lista de [participantes LPL 2026](https://lpl.qq.com/web201612/data/LOL_MATCH2_GAME_GAME237_INFO.js)
foi usada para restringir a primeira divisão; contas de Academy, Challengers
ou pessoas sem vínculo atual confirmado não foram admitidas.

A associação publicada por Mauro foi confrontada com metadados da própria
plataforma, sem gerar IDs por semelhança de nomes:

- **SOOP:** estação com `userId` exato, número válido, nome e selo **Pro Gamer**.
  O adaptador existente confirmou a estação antes de interpretar `RESULT=0`
  do player como offline. Os 16 novos jogadores passaram por ambas as consultas.
- **Huya:** os links de vídeo publicados pela fonte identificam o UID do dono;
  esse UID foi comparado com `TT_PROFILE_INFO.lp` da sala. O alias `bjh369`
  foi resolvido para **520369**. Foram usados apenas IDs numéricos canônicos,
  e o adaptador confirmou sala, estado e ausência de replay nas três contas.
  O apelido antigo `JDG.369` não foi usado como evidência de equipe atual.
- **Bilibili:** os cinco links da fonte são perfis `space.bilibili.com`, não
  salas de live. `getRoomInfoOld?mid=...` resolveu cada perfil para a sala;
  `get_info` e `get_anchor_in_room` confirmaram UID e sala. Os perfis têm
  certificação de jogador da BLG. No caso de Viper, o campo legado de
  certificação era inconsistente; o cartão público `x/web-interface/card`
  confirmou `Official.type=0`, identidade e título de jogador BLG. Cada sala
  foi consultada novamente pelo adaptador de status, com resposta offline válida.

Os identificadores, nomes de proprietário, selos e URLs consultadas estão em
[evidências estruturadas](streamers_expansion_evidence.json). Não foram guardados
cookies, tokens ou URLs de acesso a mídia.

## Jogadores acrescentados

Verificação consolidada em **16/11/2026, 16:49:58 UTC**. Em todas as linhas abaixo,
**confirmado/offline** significa vínculo e associação conferidos e estado
offline reconhecido pelo adaptador real; não significa que uma nova sessão ou
uma notificação real tenha sido observada.

| Jogador | Equipe / liga | Posição | Plataforma | Canal canônico | Estado / verificação | Elenco oficial |
| --- | --- | --- | --- | --- | --- | --- |
| Raptor | BNK FearX / LCK | JUNGLE | SOOP | [jun25jin](https://play.sooplive.com/jun25jin) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER3766_INFO.js) |
| Siwoo | Dplus KIA / LCK | TOP | SOOP | [siwoojun1234](https://play.sooplive.com/siwoojun1234) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1000866_INFO.js) |
| Lucid | Dplus KIA / LCK | JUNGLE | SOOP | [tagada008](https://play.sooplive.com/tagada008) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER4432_INFO.js) |
| ShowMaker | Dplus KIA / LCK | MID | SOOP | [showmakerr](https://play.sooplive.com/showmakerr) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER2832_INFO.js) |
| Smash | Dplus KIA / LCK | ADC | SOOP | [tlsrmawo](https://play.sooplive.com/tlsrmawo) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1000838_INFO.js) |
| Career | Dplus KIA / LCK | SUPPORT | SOOP | [pro20040829](https://play.sooplive.com/pro20040829) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1000668_INFO.js) |
| Ruler | Gen.G / LCK | ADC | SOOP | [pwh9811](https://play.sooplive.com/pwh9811) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER643_INFO.js) |
| PerfecT | KT Rolster / LCK | TOP | SOOP | [nsmin1243](https://play.sooplive.com/nsmin1243) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER4436_INFO.js) |
| Cuzz | KT Rolster / LCK | JUNGLE | SOOP | [yhk7737](https://play.sooplive.com/yhk7737) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1512_INFO.js) |
| Bdd | KT Rolster / LCK | MID | SOOP | [s735258](https://play.sooplive.com/s735258) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1231_INFO.js) |
| Effort | KT Rolster / LCK | SUPPORT | SOOP | [dltkdgh2000](https://play.sooplive.com/dltkdgh2000) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1876_INFO.js) |
| Doran | T1 / LCK | TOP | SOOP | [choi15778](https://play.sooplive.com/choi15778) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER2829_INFO.js) |
| Oner | T1 / LCK | JUNGLE | SOOP | [ansguswns519](https://play.sooplive.com/ansguswns519) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER3832_INFO.js) |
| Faker | T1 / LCK | MID | SOOP | [leesh2148](https://play.sooplive.com/leesh2148) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1651_INFO.js) |
| Peyz | T1 / LCK | ADC | SOOP | [rlantnghks](https://play.sooplive.com/rlantnghks) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER4002_INFO.js) |
| Keria | T1 / LCK | SUPPORT | SOOP | [fbalstjr1234](https://play.sooplive.com/fbalstjr1234) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER3139_INFO.js) |
| Breathe | Anyone's Legend / LPL | TOP | Huya | [390001](https://www.huya.com/390001) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER3519_INFO.js) |
| Bin | Bilibili Gaming / LPL | TOP | Bilibili | [13914640](https://live.bilibili.com/13914640) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER2687_INFO.js) |
| Xun | Bilibili Gaming / LPL | JUNGLE | Bilibili | [26808302](https://live.bilibili.com/26808302) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER3114_INFO.js) |
| Viper | Bilibili Gaming / LPL | ADC | Bilibili | [1880715130](https://live.bilibili.com/1880715130) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER193_INFO.js) |
| ON | Bilibili Gaming / LPL | SUPPORT | Bilibili | [26808227](https://live.bilibili.com/26808227) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER3509_INFO.js) |
| 369 | Top Esports / LPL | TOP | Huya | [520369](https://www.huya.com/520369) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER2147_INFO.js) |
| Tian | Top Esports / LPL | JUNGLE | Huya | [594877](https://www.huya.com/594877) | Confirmado / offline | [ficha](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1458_INFO.js) |

Canal adicional, sem contar um novo jogador: **knight — Bilibili Gaming / LPL,
MID — Bilibili [31934797](https://live.bilibili.com/31934797)**. Perfil
[3546597304568306](https://space.bilibili.com/3546597304568306), titular e
certificação BLG conferidos, estado offline válido. Sua conta Huya continua
cadastrada. A deduplicação existente funciona por conta e sessão; uma transmissão
simultânea do mesmo jogador em duas plataformas pode gerar dois avisos.

A fonte chama **Breathe** de “Breathee” e o associa à IG; a ficha individual e
o elenco oficial consultados indicam **Anyone's Legend (AL)**. O cadastro usa
AL e o nome competitivo oficial, mantendo a associação da sala confirmada pelo
UID. Não foi importado automaticamente o campo de equipe do site de streamers.

## Candidatos não cadastrados e limites

- **Aiming e BeryL:** estações SOOP existem e o status é consultável, mas a
  associação atual a uma escalação Tier 1 não foi confirmada nas fontes de
  elenco consultadas. A fonte aponta KT e DK, respectivamente; os elencos
  primários atuais consultados incluem Jiwoo (KT ADC) e Career (DK Support).
  Ausência nessas listas não prova aposentadoria ou fim de contrato, mas não
  permite admitir esses candidatos com segurança.
- **CHZZK:** os sete canais da fonte foram investigados. Metadados públicos
  identificam Zeus, Kanavi, Zeka, Gumayusi, Delight e Diable com marca de
  verificação; Peanut não tinha a marca e a fonte não informava equipe.
  Isso não valida a consulta de live: o adaptador existente usa a API oficial
  autenticada e **CHZZK_CLIENT_ID/CHZZK_CLIENT_SECRET estão ausentes**. Não
  foram adicionadas contas CHZZK nem alterado o adaptador. Peanut também ficou
  sem vínculo Tier 1 atual confirmado. Os IDs pesquisados estão no arquivo de
  evidências, separados do catálogo operacional.
- **Douyu:** não há associação na fonte indicada. Não foi encontrada nesta
  pesquisa evidência suficiente para uma nova conta, nem reaproveitados aliases
  antigos sem confirmação atual. O adaptador já existente foi preservado.
- **Twitch:** as 29 entradas estão fora das plataformas solicitadas e não foram
  importadas. Nenhum streamer foi admitido apenas por constar no site.
- **Bilibili:** os cinco IDs canônicos retornaram estado válido nesta rodada.
  As respostas 412 da investigação anterior continuam sendo um risco externo;
  não se afirma que resolver IDs tenha eliminado sua causa. O monitor mantém
  tratamento de bloqueios e estado desconhecido, sem contornar desafios.
- Todos os **24 novos canais estavam offline**. Não foi observada uma transição
  natural para live, nem enviada mensagem real ao Discord. A aptidão indicada
  é de consulta pelo monitor, condicionada ao acesso de rede da implantação e
  à configuração de uma assinatura de canal. Não garante frequência de uso
  das contas pelos jogadores.

As datas originais dos dez jogadores não foram renovadas. Os novos registros
seguem a revisão de elenco em até sete dias. **Flandre (anterior) e Viper
(novo) exigem nova revisão antes de 17/11/2026 às 00:00 UTC**; seus prazos foram
mantidos/limitados conservadoramente para o período de mudanças de elenco, sem
inferir renovação de contrato. No vencimento serão excluídos automaticamente;
sem revisão, a contagem cai para 31 jogadores/32 canais. Os demais novos
cadastros expiram em 23/11/2026 às 16:49:58 UTC. Nenhuma data é renovada só por
uma consulta de status bem-sucedida.

## Validação executada

- **122 testes passaram** na suíte completa (`unittest discover -s tests -v`),
  incluindo transições, reinício, persistência, deduplicação, notificações com
  Discord simulado, protocolos e carregamento das extensões.
- Consultas externas usaram HTTP assíncrono e os adaptadores existentes, com
  limites e timeouts; 16 novas contas SOOP, três Huya e cinco Bilibili retornaram
  estado reconhecido. HTTP 200 isolado não foi considerado suficiente.
- O carregador real aceitou **33 jogadores/34 contas**, sem exclusões no momento
  da verificação, com todas as posições e sem canais duplicados.
- Comparação com o catálogo anterior confirmou preservação dos dez jogadores e
  de seus canais. Hashes SHA-256 confirmaram que todos os arquivos Python
  existentes antes desta ampliação permaneceram iguais. Também foi conferida
  a exclusão automática dos dois registros com prazo mais curto.
- `git diff --check` passou. Nenhum bot permanente foi iniciado, nenhum banco
  de produção foi modificado e nada foi publicado no GitHub ou Square Cloud.

Comando de testes (token fictício, sem acesso ao Discord):

```bash
DISCORD_TOKEN=offline-test-only PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m unittest discover -s tests -v
```
