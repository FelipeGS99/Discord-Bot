# Lives profissionais de LoL

O comando `?prolives` monitora contas **confirmadas** de jogadores profissionais
de LoL: plataformas asiáticas para LCK/LPL Tier 1 e **Twitch de qualquer região**.
Aceita TOP, JUNGLE, MID, ADC e SUPPORT, sem filtro de nacionalidade. Associações
são cadastradas por fontes explícitas e identidade da plataforma, sem deduzir
contas pelo nickname. Candidatos não confirmados ficam visíveis como pendentes.

## Estado da entrega e dados necessários

O catálogo `pro_lives_roster.json` contém **62 jogadores registrados** em
16/11/2026: **59 jogadores prontos para monitorar, em 60 canais** (20 SOOP, nove
Huya, cinco Bilibili e 26 Twitch), além de três contas Twitch pendentes. A
[ampliação Twitch](twitch_expansion.md) documenta as 29 contas pesquisadas, a
validação online/offline e as limitações. Os 33 jogadores e 34 canais anteriores
foram preservados integralmente, cobrindo todas as posições.
Na [auditoria posterior dos 34 canais](pro_lives_audit.md), os vínculos e as
titularidades foram reconferidos, contas históricas foram sinalizadas e o parser
Bilibili recebeu validação mais estrita. Os cinco jogadores Bilibili estavam
offline; online e replay foram reconhecidos com controles públicos externos ao
catálogo. Nenhuma transição natural desses jogadores foi observada.
A [ampliação com Mauro Garih](streamers_expansion.md) acrescentou 23 jogadores e
24 contas aos dez cadastros anteriores. As 24 contas novas retornaram offline
válido pelo monitor; online SOOP foi validado anteriormente com um controle
público fora do catálogo. Não foi observada uma nova sessão de um jogador nem
enviado alerta real ao Discord. As contas Bilibili são salas canônicas, com
perfil titular e certificação conferidos, não IDs de perfil usados como sala.

Veja a [correção SOOP](soop_integration.md), a
[pesquisa inicial](pro_lives_verification.md) e a
[tabela atual de novos canais e exclusões](streamers_expansion.md).
Isso é cobertura parcial, não uma lista completa dos jogadores das duas ligas.
Flandre e Viper continuam monitorados após 17/11/2026 às 00:00 UTC. Esse prazo
gera apenas aviso de revisão. A inclusão de Twitch também preserva essa regra
de continuidade; uma revisão vencida nunca exclui uma conta confirmada.
Não confundir uma associação confirmada com uma integração operacional validada.

Uma pessoa deve revisar fontes oficiais de liga/equipe/jogador e preencher o
catálogo. São necessárias duas evidências: vínculo atual com a primeira divisão
e associação explícita do jogador ao canal. Não usar semelhança de nomes, páginas
de fãs ou contas de torneios como prova. Registrar também jogadores elegíveis
sem canal confirmado, com `channels: []`, para expor lacunas de cobertura.
O bot valida formato/escopo/datas; **não certifica o conteúdo das fontes** nem
descobre transferências automaticamente. Atualize o catálogo a cada transferência
e no máximo semanalmente. Não há promessa de cobertura completa enquanto esses
dados não forem fornecidos e revisados.

## Comandos

- `?prolives canal #lives`: configura um canal por servidor; exige Gerenciar canais.
- `?prolives parar`: cancela a assinatura deste servidor e alertas pendentes.
- `?prolives status`: mostra cobertura, canal, última consulta, avisos de revisão e erros.
- `?prolives jogadores`: lista contas prontas e pendentes separadamente, com
  motivos e indicação de revisão quando necessário.
- `?prolives recarregar`: relê os dados locais; exige Gerenciar canais.

O prefixo real é `BOT_PREFIX` (padrão `?`). São comandos de prefixo, seguindo a
arquitetura existente, sem sincronização de comandos slash ou publicação.
O bot precisa de Ver canal, Enviar mensagens e Inserir links no canal de destino.

## Formato do catálogo

Este exemplo é **sintético**, não identifica um jogador nem canal real e não deve
ser instalado como cadastro. Substitua todos os dados por evidências verificadas:

```json
{
  "schema_version": 1,
  "players": [
    {
      "id": "identificador-estavel-do-jogador",
      "name": "Nome competitivo confirmado",
      "team": "Equipe atual confirmada",
      "league": "LCK",
      "division": 1,
      "role": "MID",
      "active": true,
      "competitive_status": "tier1",
      "contract_status": "unknown",
      "verified_at": "2026-11-16T12:00:00Z",
      "valid_until": "2026-11-23T12:00:00Z",
      "roster_sources": ["https://example.com/anuncio-oficial-do-elenco"],
      "channels": [
        {
          "platform": "soop",
          "channel_id": "ID_CONFIRMADO",
          "verified_at": "2026-11-16T12:00:00Z",
          "source_urls": ["https://example.com/perfil-oficial-com-link-do-canal"]
        }
      ]
    }
  ]
}
```

- `verified_at`/`valid_until` exigem fuso. `valid_until` é o prazo para revisar
  evidências, não o término do contrato. Vencimento, datas futuras/inconsistentes
  e intervalo superior a sete dias geram avisos, sem excluir o jogador.
- Verificações de canais com mais de 30 dias ou data futura também geram aviso,
  preservando a conta confirmada. Não é necessário renovar datas para manter
  o monitoramento. Não altere datas sem uma revisão real das fontes.
- LCK: `soop` (ID do canal) ou `chzzk` (ID hexadecimal de 32 caracteres).
- **Qualquer região:** `twitch`, com login canônico minúsculo de 1–25 caracteres
  (`a-z`, `0-9`, `_`) e `user_id` numérico confirmado. O UID permite detectar
  renomeação ou troca de titular; não é substituído por similaridade de nome.
  O escopo Twitch não exige contrato atual nem `division=1`; os novos cadastros
  usam `division=null` e situação competitiva em revisão quando não confirmada.
  Isso não amplia a elegibilidade das plataformas asiáticas para Academy.
- LPL: `huya`, `douyu`, `bilibili`, com ID **numérico canônico** da sala.
  IDs curtos/aliases que redirecionam para outra sala não são aceitos como prova.
- `monitoring_status=ready` é o padrão para contas confirmadas. Candidatos com
  `monitoring_status=pending` exigem `pending_reason` e fontes públicas; ficam
  em `Catalog.pending_accounts`, visíveis nos comandos e fora das consultas.
  Não recebem `verified_at` como se estivessem confirmados. Humanoid, Jackies e
  Nuc estão pendentes porque os logins da fonte retornaram usuário inexistente.
- Uma conta não pode pertencer a mais de um jogador. URLs não são aceitas como ID.
  UIDs Twitch repetidos também são rejeitados, inclusive sob logins diferentes.
  Erros de estrutura desativam o catálogo inteiro até a correção, sem manter
  silenciosamente uma lista antiga em uso.
- Limite operacional: 200 jogadores e 200 contas por instalação. Todas as cinco
  posições são aceitas, inclusive reservas ativos da primeira divisão quando
  seu vínculo estiver confirmado. O escopo asiático mantém LCK/LPL Tier 1;
  Twitch aceita jogadores profissionais de qualquer região. A fonte deve
  associar explicitamente a pessoa ao canal, sem importar streamers genéricos.

## Validade e status competitivo

A validade de uma revisão e a situação contratual são independentes da
participação competitiva. Contrato vencido, renovação não confirmada, falta de
atualização ou saída de uma equipe não constituem, sozinhos, confirmação de
saída do cenário Tier 1. Nenhum endpoint de live decide esse status.

- `competitive_status`: `tier1` (último vínculo confirmado), `unconfirmed`
  (em revisão) ou `out_of_scope` (saída a confirmar/documentar). Nos cadastros
  antigos, a ausência do campo preserva a classificação Tier 1 já registrada.
- `contract_status`: `unknown`, `confirmed`, `expired` ou
  `renewal_unconfirmed`. O padrão é `unknown`; esse campo nunca exclui contas.
  Os dois últimos valores geram avisos. Flandre e Viper estão com
  `competitive_status=tier1` e `contract_status=renewal_unconfirmed`, sem
  inventar confirmação de renovação ou mudar as fontes e datas anteriores.
- `active` é um campo legado. `false` sozinho gera revisão; não basta para
  desativar. Para retirar um jogador já cadastrado, uma pessoa deve confirmar
  a saída do Tier 1 e registrar `competitive_status=out_of_scope` com
  `competitive_status_confirmation`: fontes HTTPS confiáveis, motivo e data
  de confirmação efetiva (com fuso, sem ser futura). O carregador verifica a
  estrutura; a confiabilidade e o conteúdo das fontes exigem revisão humana.
- Confirmação ausente, incompleta ou ainda futura mantém o monitoramento e
  sinaliza revisão. Dados com status desconhecido, URLs/fontes inválidas,
  datas sem fuso ou outros erros de estrutura continuam sendo erros explícitos
  de configuração. Nas plataformas asiáticas, registros fora de LCK/LPL e
  divisão 1 continuam fora do escopo. A Twitch admite todas as regiões; as
  cinco posições e a identificação de jogador profissional continuam necessárias.

Exemplo **sintético** de campos a acrescentar a um registro após uma saída
confirmada, como transferência para Academy ou aposentadoria anunciada:

```json
{
  "competitive_status": "out_of_scope",
  "competitive_status_confirmation": {
    "verified_at": "2026-11-16T18:00:00Z",
    "reason": "Transferência para Academy confirmada pela equipe",
    "sources": ["https://example.com/anuncio-oficial-de-saida"]
  }
}
```

Uma transferência entre equipes Tier 1 das duas ligas exige atualização do
cadastro, não confirmação de saída do cenário. Fontes antigas de ingresso na
equipe não comprovam uma saída. Não use rumor ou vencimento contratual como
motivo de exclusão. A confirmação explícita de saída não expira automaticamente;
um retorno exige nova revisão e atualização do status competitivo.

Os avisos ficam em `Catalog.review_warnings`, aparecem em `?prolives status`
e são contabilizados na cobertura e em `?prolives recarregar`. A lista de
jogadores marca `[revisao pendente]`. Não se enviam avisos de contrato como
notificações de live ou mensagens automáticas repetidas no canal assinado.

IDs de jogadores/contas, `Account.key`, tabelas SQLite e regras de deduplicação
permanecem os mesmos. A expiração de uma revisão não apaga histórico, não cria
uma nova referência de estado e não cancela entregas pendentes. A saída
competitiva confirmada suspende consultas e entregas desse jogador, preservando
o cadastro e o histórico. As retenções operacionais já existentes (alertas
pendentes por 30 minutos e histórico por 30 dias) permanecem iguais.

## Plataformas e verificação em 16/11/2026

As consultas abaixo foram feitas pelo proxy HTTPS deste ambiente. Salas públicas
usadas para testar os protocolos não foram associadas a jogadores no catálogo.
Endpoints de site não equivalem a APIs públicas com contrato de estabilidade.

| Plataforma | Método implementado | Evidência e limitações |
| --- | --- | --- |
| Twitch | HTML público para identificar o cliente do site + POST `https://gql.twitch.tv/gql`, lotes de até 20 contas | 26 contas de jogador offline e controle público online reconhecidos. Login e UID precisam coincidir; `user=null`, erro HTTP/GraphQL e lote incompleto são desconhecidos. Sem cadastro de aplicativo, token de usuário ou navegador. Endpoint interno público, sujeito a mudanças. [Validação e tabela](twitch_expansion.md). |
| SOOP | GET `https://api-channel.sooplive.com/v1.1/channel/{id}/station` e POST `https://live.sooplive.com/afreeca/player_live_api.php`, modo live | A estação precisa existir e corresponder ao ID solicitado. Só então `RESULT=0` é offline. Online exige `RESULT=1`, `BJID` correspondente e `BNO` válido. Os quatro jogadores originais e 16 novos tiveram offline reconhecido; controle público online reconhecido na correção anterior. Restrições e erros são desconhecidos. [Diagnóstico e validação](soop_integration.md). |
| CHZZK | API oficial `GET https://openapi.chzzk.naver.com/open/v1/lives`, paginação de 20 | Documentação oficial acessível; consulta sem autenticação retornou 401. Exige `CHZZK_CLIENT_ID` e `CHZZK_CLIENT_SECRET`, de aplicação registrada. Essas variáveis estavam ausentes. Metadados públicos de sete canais foram conferidos na ampliação; isso não valida a API de estado autenticada. Não usa a API interna de estado não documentada. **Fluxo autenticado não validado.** |
| Huya | HTML de `https://www.huya.com/{room_id}`, objeto JSON `TT_ROOM_DATA` | Página de controle respondeu 200 com estado e `liveId`. Parse estrito, rejeitando replay e sala divergente. A antiga rota `cache.php?...profileRoom` retornou HTML, portanto não é usada como API JSON. Método de site sujeito a mudanças e bloqueios. |
| Douyu | JSON do site `https://www.douyu.com/betard/{room_id}` | Controle respondeu 200, com `room_id`, `show_status`, `videoLoop` e `show_id`. Replays são excluídos. Endpoint não tem garantia pública de estabilidade. |
| Bilibili | `https://api.live.bilibili.com/room/v1/Room/get_info?room_id=...` | Na ampliação, cinco salas canônicas tiveram titular/identidade conferidos e estado offline reconhecido pelo adaptador. A investigação anterior registrou bloqueios **412** e alias divergente, que foi rejeitado. Sucesso atual não elimina o risco de bloqueio intermitente. Perfil `space.bilibili.com` não é ID de sala. Não tenta resolver desafios, obter cookies ou contornar bloqueios. `live_status=2` é replay. |

Fontes técnicas:

- [CHZZK Live (oficial)](https://chzzk.gitbook.io/chzzk/chzzk-api/live)
- [CHZZK autenticação e formato de resposta (oficial)](https://chzzk.gitbook.io/chzzk/chzzk-api/tips)
- [Cliente SOOP mantido pelo Streamlink](https://github.com/streamlink/streamlink/blob/master/src/streamlink/plugins/soop.py)
- [Cliente Huya mantido pelo Streamlink](https://github.com/streamlink/streamlink/blob/master/src/streamlink/plugins/huya.py)

Na pesquisa inicial, Leaguepedia/Fandom retornou 402 e algumas páginas antigas
de equipes retornaram 403/404. A pesquisa posterior localizou os dados oficiais
de membros ativos da LPL, a página atual da Gen.G e a URL correta do elenco da
T1 (`https://www.t1.gg/teams/leagueoflegends`). O relatório de verificação registra
as evidências atuais; links antigos não foram considerados indisponíveis sem
investigar seus destinos atuais.

## Operação e confiabilidade

O Cog carrega automaticamente pelo `bot.py`. Usa `aiohttp`, já requerido por
`discord.py`, e `sqlite3` da biblioteca padrão: não acrescenta serviço nem
dependência de navegador. Compatível com Python 3.12 deste projeto e execução
via `python main.py` na Square Cloud. O SQLite fica em `pro_lives.sqlite3`,
ignorado pelo Git. Preserve-o em armazenamento persistente entre reinícios e
deploys; sem ele, perde-se o histórico de deduplicação.

Consultas a cada quatro minutos, assíncronas, até quatro requisições simultâneas
e no máximo uma requisição por segundo por plataforma. Timeout HTTP: 12s;
limite de um ciclo de consultas: 210s. Erros HTTP/rede têm espera exponencial,
e 429 respeita `Retry-After`. Esperas e I/O SQLite não bloqueiam o event loop.
SOOP faz duas requisições por conta/ciclo: identidade da estação e estado da live.
Uma estação SOOP inexistente (404) não suspende as consultas dos outros jogadores.
Os limites são conservadores; não representam uma quota oficial contratada.
Falhas podem aumentar o intervalo efetivo de detecção. Não há consultas sem
assinatura de servidor e contas válidas.

A CHZZK só oferece a lista global de lives nesse endpoint; é percorrida até o
fim, com teto de 80 páginas. Lista incompleta/erro vira estado desconhecido para
todos os alvos, nunca offline. Erros nas outras plataformas ficam isolados por
conta/plataforma. Nenhuma falha substitui o último estado válido por offline.

O primeiro estado válido de cada conta é uma referência, sem anúncio retroativo.
Depois disso, offline→live ou mudança do identificador de sessão geram alerta.
O estado e a fila por servidor/canal/sessão são transacionais no SQLite. Envio
que falha em um servidor não impede os demais; é tentado novamente após uma
consulta válida, por até 30 minutos, desde que ainda seja a mesma live e o canal
continue assinado. Histórico enviado expira após 30 dias. Em queda exatamente
entre o envio ao Discord e a confirmação no SQLite, pode haver duplicação;
a API do Discord e SQLite não compartilham uma transação.

O cliente preserva proxy e confiança TLS do ambiente (`trust_env=True`). Isso
vale para as plataformas desta funcionalidade. A necessidade de proxy do
cliente Discord existente, observada no teste anterior, é independente deste
recurso e não foi alterada aqui. Não coloque tokens em arquivos versionados,
logs, comandos de chat ou documentação. Credenciais da CHZZK devem entrar como
variáveis seguras do processo. Garanta acesso aos hosts listados acima na
política de saída da implantação.

## Validação local

A ampliação Twitch passou na suíte completa com **155 testes**, incluindo
13 novos testes da plataforma e os testes anteriores de validade. Os testes
conferem a preservação dos 33 jogadores/34 canais após 17/11, após o prazo de todas as revisões e
em fevereiro/2027; avisos nos comandos; saída competitiva documentada; alertas
pendentes e deduplicação após vencimento e reinicialização. A comparação do
catálogo confirmou preservação de todos os dados anteriores, canais, fontes,
datas e IDs. Na Twitch também cobrem identidade numérica, pendências visíveis,
lotes, cache, online/offline, erros HTTP, isolamento e deduplicação após reinício.

```bash
cd /workspace/Discord-Bot
DISCORD_TOKEN=offline-test-only .venv/bin/python -m unittest discover -s tests -v
```

Os testes usam dados sintéticos e HTTP local para cobrir protocolos, elegibilidade,
concorrência, transições, reinício, deduplicação, repetição de envio e bloqueios.
Não exigem tokens reais nem enviam mensagens. Para um teste real de ponta a ponta,
primeiro forneça catálogo confirmado, credenciais necessárias e um canal de
teste autorizado; observe uma nova sessão real após estabelecer a referência.
Não foi enviada notificação real nem feito deploy nesta implementação.
