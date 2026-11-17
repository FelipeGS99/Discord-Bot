# Verificação de elencos e canais — 16/11/2026

> Atualização de política: prazos de verificação agora geram avisos e mantêm
> os 33 jogadores/34 canais. Referências abaixo a exclusão automática por
> vencimento descrevem o comportamento anterior. Veja a
> [regra atual de status competitivo e revisão](pro_lives.md#validade-e-status-competitivo).

> Registro histórico da etapa anterior, com dez jogadores. O estado atual e
> os 23 novos jogadores estão na [ampliação do catálogo](streamers_expansion.md).

Na etapa de pesquisa de elencos foram alterados somente o catálogo e a documentação.
Posteriormente, a [integração SOOP foi corrigida e validada](soop_integration.md).
Nenhum segredo, configuração de canal, banco de produção ou implantação foi alterado.
Não houve publicação no GitHub/Square Cloud nem envio de notificações.

## Resultado utilizável

**10 jogadores prontos para consulta de estado no monitor: seis Huya e quatro
SOOP.** Antes da correção, SOOP retornava estado desconhecido porque faltava
validar a estação antes de interpretar `RESULT=0`. A validação posterior confirmou
os quatro jogadores offline e identificou uma transmissão pública de controle
online, fora do catálogo. As seis contas Huya cobrem todas as posições.

O catálogo contém 10 jogadores e 10 contas. Nenhuma das seis consultas Huya
indicou live. Não se afirma uso regular/exclusivo desses canais nem validação
de uma transição real ao vivo. Algumas contas são históricas e ficaram longos
períodos sem transmissão, mesmo mantendo a identidade correta na plataforma.

| Jogador | Equipe atual / liga | Posição | Plataforma | Canal canônico | Verificação |
| --- | --- | --- | --- | --- | --- |
| Flandre | Bilibili Gaming / LPL | TOP | Huya | [913004](https://www.huya.com/913004) | Anúncio oficial + identidade atual conferida; consulta válida, offline |
| Jiejie | EDward Gaming / LPL | Jungle | Huya | [913005](https://www.huya.com/913005) | Anúncio oficial + identidade atual conferida; consulta válida, offline |
| knight | Bilibili Gaming / LPL | MID | Huya | [969689](https://www.huya.com/969689) | Link biográfico `knight9` corresponde ao mesmo ID/host; consulta válida, offline |
| JackeyLove | Top Esports / LPL | ADC | Huya | [111800](https://www.huya.com/111800) | Gravação de outubro/2026 aponta explicitamente o canal; identidade atual compatível; consulta válida, offline |
| Meiko | Invictus Gaming / LPL | Support | Huya | [913001](https://www.huya.com/913001) | Anúncio oficial + identidade atual conferida; consulta válida, offline |
| TheShy | Invictus Gaming / LPL | TOP | Huya | [991111](https://www.huya.com/991111) | Link biográfico explícito + identidade atual conferida; consulta válida, offline |
| Kiin | Gen.G / LCK | TOP | SOOP | [rldls5656](https://play.sooplive.com/rldls5656) | Estação e identidade verificadas; consulta válida, offline |
| Canyon | Gen.G / LCK | Jungle | SOOP | [rjsqn0618](https://play.sooplive.com/rjsqn0618) | Estação e identidade verificadas; consulta válida, offline |
| Chovy | Gen.G / LCK | MID | SOOP | [wlgnsdl0303](https://play.sooplive.com/wlgnsdl0303) | Estação e identidade verificadas; consulta válida, offline |
| Duro | Gen.G / LCK | Support | SOOP | [jmg3495](https://play.sooplive.com/jmg3495) | Estação e identidade verificadas; consulta válida, offline |

Não foi possível cadastrar uma associação atual suficientemente comprovada para
Douyu ou Bilibili, nem estabelecer vínculo independente dos candidatos CHZZK.
Esses resultados não significam que os jogadores não tenham canais nessas redes.

## Evidência dos dez cadastros

Para os seis jogadores LPL, foram consultados tanto `activePlayers` da equipe
quanto a ficha individual oficial, retornando equipe/posição e `UserStatus=1`.
As fichas individuais foram atualizadas pelo serviço em 16/11/2026; a data de
exportação não é tratada como data de uma transferência. O conteúdo e as
identidades foram comparados, e não apenas os nomes abreviados das equipes.

| Jogador | Fonte de vínculo e posição na LPL | Evidência de associação do canal |
| --- | --- | --- |
| Flandre | [Ficha oficial 100](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER100_INFO.js), BLG, `GamePlace=1` | [Anúncio oficial Huya de 03/12/2021](https://blog.huya.com/news/33511) cita Flandre → 913004; página atual mantém `Flandre圣枪哥` |
| Jiejie | [Ficha oficial 2770](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER2770_INFO.js), EDG, `GamePlace=5` | Mesmo anúncio cita Jiejie → 913005; página atual mantém `Jiejie` |
| Meiko | [Ficha oficial 5](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER5_INFO.js), IG, `GamePlace=4` | Mesmo anúncio cita Meiko → 913001; página atual mantém `Meiko`, com título sobre aniversário da IG |
| knight | [Ficha oficial 2562](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER2562_INFO.js), BLG, `GamePlace=2` | [Biografia de 卓定](https://zh.wikipedia.org/wiki/%E5%8D%93%E5%AE%9A) vincula `huya.com/knight9`; a sala atual informa `privateHost=knight9` e `profileRoom=969689` |
| TheShy | [Ficha oficial 1478](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1478_INFO.js), IG, `GamePlace=1` | [Biografia de 姜承録](https://zh.wikipedia.org/wiki/%E5%A7%9C%E6%89%BF%E9%8C%B2) vincula explicitamente 991111; página atual mantém TheShy |
| JackeyLove | [Ficha oficial 1832](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_MEMBER1832_INFO.js), TES, `GamePlace=3` | [Gravação datada de 10/10/2026](https://www.bilibili.com/video/BV151p36DES1/) inclui `直播间：https://www.huya.com/111800`; a página atual mantém `滔搏JackeyLove` |

O mapeamento das posições é publicado pelo próprio [cliente da LPL](https://lpl.qq.com/web201612/js/public.js):
`1=TOP`, `2=MID`, `3=ADC`, `4=SUP`, `5=JUNGLE`. Não foi deduzido pela ordem do array.

A [página oficial da Gen.G](https://geng.gg/pages/league-of-legends) informa os cinco
titulares com nome, nome civil e posição; ao lado de Kiin, Canyon, Chovy e Duro
há links SOOP individuais. Os links antigos Afreeca redirecionam para a estação
SOOP. Os metadados públicos de estação retornaram `기인2`, `Canyon_lol`, `쵸비03` e
`듀로02`, respectivamente. Ruler aparece como ADC, mas sem link SOOP/CHZZK nessa
página; não foi criado um canal para ele.

## Cobertura da pesquisa dos elencos

A [relação oficial de participantes da LPL 2026](https://lpl.qq.com/web201612/data/LOL_MATCH2_GAME_GAME237_INFO.js)
lista **14 equipes**, sem RNG nem FPX. A lista antiga de clubes e uma relação
enciclopédica ainda incluíam equipes de temporadas anteriores; não foram usadas
para admitir jogadores automaticamente. Foram consultados os arquivos oficiais
de membros ativos dessas 14 equipes e as dez equipes LCK. Os resultados abaixo
registram também lacunas, sem afirmar que um elenco incompleto é o elenco inteiro.

Os elencos que não possuem uma associação aprovada acima não foram importados
para o catálogo. Dados de fontes auxiliares são pistas, não prova suficiente de
que uma pessoa permaneça no elenco atual. Técnicos, Academy/Challengers e
streamers sem vínculo Tier 1 não foram cadastrados.


### LPL: arquivos oficiais consultados

As células mostram somente os nomes presentes em `activePlayers` do arquivo consultado. Uma célula “—” é lacuna da fonte; não autoriza deduzir que a equipe esteja sem atleta. Essa lista de pesquisa não substitui as fichas individuais verificadas dos seis cadastros.

| Equipe | TOP | Jungle | MID | ADC | Support | Fonte |
| --- | --- | --- | --- | --- | --- | --- |
| AL | Breathe | Tarzan | Shanks | Hope | Kael | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM422_INFO.js) |
| BLG | Flandre, Bin, Wenbo (situação divergente) | Xun | Knight | Viper | ON | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM57_INFO.js) |
| EDG | Zdz | Jiejie | sinian, BuLLDoG | Leave | Parukia | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM1_INFO.js) |
| IG | TheShy | Wei | Rookie | Assum, JiaQi | Meiko | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM2_INFO.js) |
| JDG | Xiaoxu | xiaofang, JunJia | HongQ | GALA | Vampire | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM29_INFO.js) |
| LGD | Burdol | Heng | Tangyuan | Shaoye | — | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM4_INFO.js) |
| LNG | sheer | Weiwei | Nia | 1xn | MISSING, Ycx | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM9_INFO.js) |
| NIP | HOYA | Guwon | Care | Photic | fengyue | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM587_INFO.js) |
| OMG | — | re0 | — | Starry | — | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM6_INFO.js) |
| WE | Cube | Monki, Tyrion | Karis | About | Erha | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM12_INFO.js) |
| TT | — | — | — | — | Feather | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM438_INFO.js) |
| TES | 369, ZUIAN | Tian | Creme | JackeyLove | Zhuo | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM42_INFO.js) |
| UP | — | — | Saber | — | Xiaoxia | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM685_INFO.js) |
| WBG | Zika | Xiaohao | Xiaohu | Elk | Jwei, Moham | [dados oficiais](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM41_INFO.js) |

RNG não foi admitida: não integra a lista oficial das 14 equipes da temporada 2026. Sua ficha de elenco encontrada ainda traz atualização de 2025 e Tangyuan, também listado pela ficha atual da LGD. FPX tampouco integra a relação de 2026.

### LCK: verificação de fontes por equipe

| Equipe | Resultado da verificação do elenco | Fonte / ressalva |
| --- | --- | --- |
| Gen.G | Kiin (TOP), Canyon (Jungle), Chovy (MID), Ruler (ADC), Duro (Support) | [página oficial com nomes e posições](https://geng.gg/pages/league-of-legends); elenco também coincide com ficha Tencent e Wikipedia |
| T1 | Doran (TOP), Oner (Jungle), Faker (MID), Peyz (ADC), Keria (Support) | [dados de membros ativos](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM692_INFO.js), [página da equipe](https://www.t1.gg/teams/leagueoflegends) e biografia da organização; sem links pessoais de streaming nessa página |
| Hanwha Life Esports | Zeus (TOP), Kanavi (Jungle), Zeka (MID), Gumayusi (ADC), Delight (Support) | [dados de membros ativos](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM20_INFO.js) e [Wikipedia](https://en.wikipedia.org/wiki/Hanwha_Life_Esports); site HLE consultado depende de aplicação JS |
| Dplus KIA | Siwoo (TOP), Lucid (Jungle), ShowMaker (MID), Smash (ADC), Career (Support) | [dados de membros ativos](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM591_INFO.js) e [Wikipedia](https://en.wikipedia.org/wiki/Dplus_KIA); site antigo da equipe inacessível no proxy |
| KT Rolster | PerfecT (TOP), Cuzz (Jungle), Bdd (MID), Jiwoo (ADC), Effort (Support) | [dados de membros ativos](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM21_INFO.js) e [Wikipedia](https://en.wikipedia.org/wiki/KT_Rolster); divergências com nomes antigos do Tracking The Pros não foram importadas |
| HANJIN BRION | Casting (TOP), GIDEON (Jungle), Roamer (MID), Teddy (ADC), Namgung (Support) | [dados de membros ativos](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM864_INFO.js), atualizados em setembro/2026; sem associação de canal aprovada nesta pesquisa |
| BNK FearX | Clear (TOP), Raptor (Jungle), VicLa / Daystar (MID), Taeyoon (ADC), Kellin (Support) | [dados de membros ativos](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM1130_INFO.js) e [Wikipedia](https://en.wikipedia.org/wiki/FearX); fonte auxiliar ainda associa Diable ao time, portanto exige atenção a transferências |
| Nongshim RedForce | Não certificado integralmente nesta pesquisa | [site oficial consultado](https://www.ns-esports.com/page/22); Wikipedia e Tracking The Pros divergem entre Scout/Fisher, Diable/Taeyoon e Sponge/GIDEON. Arquivo Tencent alternativo retornou 503; nenhum desses vínculos foi importado |
| Kiwoom DRX | Não certificado integralmente nesta pesquisa | [site oficial consultado](https://en.drx.gg/lol); arquivos e fontes auxiliares divergem entre elencos, inclusive sobre o ADC. Não foram promovidos cadastros antigos sem corroboração |
| DN SOOPers | Não certificado integralmente nesta pesquisa | [arquivo de equipe consultado](https://lpl.qq.com/web201612/data/LOL_MATCH2_TEAM_TEAM1242_INFO.js) difere substancialmente das outras fontes; faltou confirmar independentemente a composição do primeiro time |

O [Tracking The Pros](https://www.trackingthepros.com/players/) foi consultado para cruzar equipe e posição. Seus registros incluem técnicos, reservas e atletas associados a equipes antigas; não foi usado como importador automático de elegibilidade.

## Exclusões importantes

| Candidato / origem | Evidência atual | Decisão |
| --- | --- | --- |
| Viper → Huya 913002, no anúncio EDG de 2021 | A página atual informa `WEFoFo`, não Viper | Excluído; não transportar associação histórica para o proprietário atual |
| JunJia → Huya 913006, no mesmo anúncio | A página atual informa `EDG-Monki`, não JunJia | Excluído para JunJia; tampouco cadastrar automaticamente Monki sem outra evidência |
| Viper → 26130001 / 978014, ou outros resultados de busca | Há contas antigas e resultados com afiliação EDG/GRF; não foi confirmada a conta principal atual da BLG | Não cadastrado a partir de nickname ou afiliação histórica |
| `knight左手专属OB`, canais de melhores momentos de TheShy e semelhantes | Resultados de observação/gravação e fãs aparecem ao lado dos profissionais | Excluídos |
| Ruler → SOOP/CHZZK | A página oficial da Gen.G não publica link nessas plataformas para ele | Sem cadastro de canal |
| ShowMaker, Bdd, Smash e Lucid → resultados CHZZK | A busca pública retornou canais com nomes relacionados aos times, mas sem marca de verificação e sem confirmação independente da associação | Candidatos, não cadastrados |
| Teddy → resultado CHZZK `한진 브리온 테디` | A plataforma informa marca PARTNER, mas faltou um vínculo externo independente da equipe/jogador na pesquisa | Candidato, não cadastrado; não confundir parceria com confirmação independente de identidade |
| Douyu: 369, Tian, JackeyLove, knight, Tarzan, GALA e outros nomes consultados | Busca retornou perfis antigos, alguns com última live em 2019–2023, e homônimos | Nenhum cadastro baseado somente no resultado de busca |

As buscas públicas Douyu cobriram 369, Tian, JackeyLove, knight, Tarzan, Hope,
Breathe, Shanks, Elk, Xiaohu, GALA, Meiko, Jiejie, XUN e ON. O endpoint respondeu,
mas isso não comprovou associação atual. A playlist encontrada com título
“LPL选手&赛事直播单” era criada por um usuário e continha streamers fora do escopo;
não foi tratada como lista oficial.

## Estado das plataformas e próximos requisitos

- **Huya:** as seis contas cadastradas retornaram os IDs canônicos esperados e
  estado offline no adaptador `PlatformClient.check`. A resposta só confirma
  consulta e parse; não houve transmissão iniciando durante o teste.
- **Douyu:** consulta e busca acessíveis. Não há, nesta entrega, conta pessoal
  com associação suficiente para cadastro. Um endpoint funcionando não torna
  elegível todo resultado da busca.
- **SOOP:** estação validada em endpoint independente antes do POST de status;
  `RESULT=0` passou a ser reconhecido como offline nesse contexto. Os quatro
  jogadores tiveram identidade e offline confirmados. Um controle público online
  foi reconhecido com `RESULT=1`, `BJID` e `BNO` correspondentes. Ver relatório
  específico para limites da validação e testes de transição simulada.
- **CHZZK:** a busca pública retornou dados, incluindo candidatos. A API oficial
  de monitoramento continua exigindo `CHZZK_CLIENT_ID` e `CHZZK_CLIENT_SECRET`,
  ausentes no ambiente. Não foram requisitados nem armazenados valores secretos.
- **Bilibili:** busca de usuário `BLGknight` retornou HTTP 412. Uma página de
  gravação de JackeyLove respondeu 200 e serviu como evidência de seu canal Huya;
  uma gravação Bilibili não é um canal de live Bilibili. Nenhum ID de sala foi
  deduzido de ID de vídeo ou de usuário.

Uma busca geral adicional foi interrompida quando Brave retornou 429/CAPTCHA;
não houve tentativa de resolver ou contornar o desafio. Isso limitou a pesquisa
de associações adicionais, sem invalidar as fontes abertas diretamente.

## Validade e ativação

`verified_at` registra a checagem em 16/11/2026. A validade normal do snapshot é
23/11/2026, conforme a política de sete dias já implementada. Para Flandre foi
adotada revisão antecipada em **17/11/2026 00:00 UTC (16/11 às 21h de Brasília)**,
por cautela na janela de transferências. Essa data é um limite operacional de
revisão, não uma declaração de renovação ou rescisão contratual.

Antes de renovar datas, conferir novamente equipe, posição, identidade atual
da conta e ID canônico. O bot não acompanha automaticamente transferências ou
trocas de titularidade dos canais. O histórico de reatribuições acima demonstra
por que renovar datas sem reler as fontes seria incorreto.

O catálogo é relido automaticamente pelo ciclo existente de quatro minutos;
também pode ser relido por `?prolives recarregar`. Para habilitar notificações em
um servidor é preciso configurar `?prolives canal #lives`, com as permissões
documentadas. A primeira consulta estabelece uma referência sem alerta retroativo.
Nenhum canal foi escolhido, nenhum processo persistente foi iniciado e nenhuma
notificação real foi enviada nesta pesquisa. Configurar um canal agora não
publica o repositório nem realiza deploy.

## Validação executada na pesquisa inicial

- `load_catalog` aceitou os dez jogadores e dez contas, sem IDs duplicados e com
  todas as posições cobertas pelas seis contas Huya.
- Conferidas fontes obrigatórias, IDs canônicos e ausência dos IDs reatribuídos
  913002 e 913006 no catálogo de produção.
- Executado o adaptador real contra os dez canais: seis respostas Huya válidas
  offline; quatro respostas SOOP inconclusivas, registradas como tal.
- Suíte completa: **109 testes passaram**, incluindo o carregamento e
  descarregamento das extensões e os testes de deduplicação existentes.
- `git diff --check` passou. Nenhum segredo ou token foi colocado nos dados.

A validação posterior da correção SOOP está descrita em [soop_integration.md](soop_integration.md);
os resultados inconclusivos acima registram a etapa anterior, não o estado atual.
