# Tigrão — LoL Live Tracker

O módulo usa somente APIs de servidor: Riot Account-V1, Spectator-V5, Match-V5,
League-V4, Champion-Mastery-V4 e Data Dragon. Nenhum programa, League Client API
ou agente precisa ser instalado no computador dos jogadores.

## Configuração

1. No cofre/configuração de variáveis do servidor do bot, vincule a chave oficial
   da Riot à variável **RIOT_API_KEY** do processo. Não coloque a chave no código,
   no Git ou em mensagens do Discord. Reinicie o bot após alterar o vínculo.
   Chaves de desenvolvimento da Riot expiram e precisam ser renovadas; uma chave
   autorizada para o aplicativo é necessária para operação contínua.
2. Garanta saída HTTPS para `americas.api.riotgames.com`,
   `br1.api.riotgames.com` e `ddragon.leagueoflegends.com` com TLS verificado.
   Os clientes preservam proxy e confiança CA do ambiente (`trust_env=True`).
3. No servidor Discord, execute `?loltrack canal #live-match`.
4. Execute `?loltrack seguir Mochila#bunny`.

O prefixo dos exemplos é `?`, respeitando `BOT_PREFIX` quando personalizado.
O grupo é **loltrack**. Todos os comandos anteriores em **lol**, CS2, Valorant,
futebol, Telegram e lives profissionais são preservados, incluindo `lol canal`.

## Comandos

| Comando | Comportamento |
|---|---|
| `?loltrack canal #live-match` | Persiste um canal por servidor; trocar o canal redireciona notificações futuras, inclusive relatórios pendentes. |
| `?loltrack seguir Nome#TAG` | Resolve a conta oficial por Riot ID, salva PUUID e acompanha automaticamente em BR1. Cadastro repetido não duplica o jogador. |
| `?loltrack deixar Nome#TAG` | Desativa somente aquela conta neste servidor e cancela suas notificações pendentes. Reativar não ressuscita relatórios antigos. |
| `?loltrack lista` | Lista contas ativas/inativas e o estado da última consulta. |
| `?loltrack status` | Mostra tarefa, quantidade de jogadores, canal, saúde Riot, última verificação e ocorrência recente. |
| `?loltrack teste` | Envia **três mensagens** ao canal configurado: Live Match, build com imagens e relatório final. Tudo está marcado **MODO TESTE**. Não exige chave Riot. |

Configuração, seguir, deixar e teste exigem dono, Administrador ou **Gerenciar
servidor**. Lista/status exigem contexto de servidor. O bot precisa de Ver canal,
Enviar mensagens, Inserir links/embeds e Ler histórico. O teste tem intervalo de
60 segundos por servidor e nunca escolhe um destino desconhecido.

BR1 é o padrão dos comandos. O cliente e o banco têm plataforma por conta e
roteamento regional separado para permitir expansão futura sem alterar o esquema.
As contas já cadastradas são carregadas automaticamente após reinícios; não é
necessário executar comandos para detectar cada nova partida.

## Monitoramento e confiabilidade

- A tarefa inicia com o bot e espera o Discord ficar pronto. O ciclo começa a
  cada aproximadamente 60 segundos. O tempo aumenta conforme quantidade de
  jogadores, enriquecimento e limites da Riot; não há garantia de baixa latência
  sob cotas restritas.
- Uma consulta Spectator é compartilhada quando a mesma conta é seguida por
  múltiplos servidores. A notificação Live Match é enviada primeiro, sem esperar
  todas as consultas históricas, e depois editada com os dados coletados.
- Vários jogadores do mesmo servidor na mesma partida recebem um Live Match
  compartilhado e builds individuais. O relatório agrupa até quatro jogadores
  por mensagem para respeitar o limite de embeds do Discord.
- `404` de Spectator é ausência de partida e comprova uma resposta normal do
  serviço; erros de autenticação, rede ou cota preservam o estado anterior.
- Quando todos os acompanhados deixam aquela partida, a Match-V5 é consultada
  pelo ID exato. Resultado ainda não publicado (`404`) permanece pendente para
  outro ciclo, inclusive após reinício ou se o jogador entrar em outra partida.
- HTTP 401/403 informa chave inválida/expirada/sem autorização e aplica uma pausa.
  HTTP 429 respeita `Retry-After`; limites e contagens de aplicação ajustam o
  intervalo. Há uma trava compartilhada para requisições e espaçamento inicial
  de 1,25 segundo (conservador para uma cota de 100/120s). Erros 5xx e de rede têm
  no máximo três tentativas com backoff. Os timeouts HTTP são limitados.
- Cadastros, configuração e fases usam transações SQLite em threads. Envio e
  confirmação são separados: uma falha não marca a mensagem como entregue.
  No reinício, marcadores nos embeds são procurados nas últimas **100 mensagens**
  do canal para recuperar a janela entre enviar e confirmar no banco. A
  recuperação não garante exatamente uma entrega se a mensagem saiu dessa janela
  ou se o histórico foi apagado. Preserve Ler histórico e evite executar duas
  instâncias do monitor ao mesmo tempo.
- Sem canal configurado não há consultas do tracker nem notificações. Trocar o
  destino não reenvia mensagens já entregues. Todas as saídas automáticas são
  conferidas contra o servidor e canal configurados; menções são desativadas.
- Spectator não fornece kills, ouro e inventário ao vivo como uma transmissão de
  telemetria. O módulo não fabrica esses números: estatísticas de WR/KDA são
  **históricas**, com tamanho da amostra visível.

## Dados e apresentação

Live Match mostra campeões, times, modo e horário/duração quando disponíveis.
O histórico recente consulta até cinco partidas anteriores por participante
identificável e calcula WR e KDA; não inclui o jogo atual na comparação. Elo e
maestria são consultados quando permitidos. Dados ausentes ficam explicitamente
indisponíveis. As identidades omitidas por Spectator não são resolvidas por outra
API para desanonimizar participantes.

A apresentação usa imagens oficiais e metadados do Data Dragon, com cache de
seis horas. Histórico, elos, maestria e resultados também usam caches com prazos
específicos. O primeiro enriquecimento dos dez participantes pode levar mais de
um minuto sob cotas de desenvolvimento; o Live Match inicial já terá sido enviado.
O catálogo não é um provedor de estatísticas de builds.

**Builds são heurísticas**, identificadas no embed, sem win rates inventados:
perfil do campeão, rota somente se fornecida, composição inimiga e tendências de
dano/cura/tanques orientam botas, três itens principais e alternativas defensivas.
Os itens precisam existir e ser compráveis no patch/mapa do catálogo atual.
As classes dos campeões são aproximações e não medem o dano real nem todo o kit
de controle de grupo. Quando não há dados suficientes, isso é informado; não se
apresenta uma ordem como estatisticamente otimizada. Não há runas, scraping ou
uso de sites externos de builds. Modos fora de Summoner's Rift/ARAM não têm guia
heurístico validado. Uma fonte estatística licenciada pode substituir estas regras
futuramente, sem atribuir estatísticas ao Data Dragon.

O pós-partida usa os dados oficiais: vitória/derrota, campeão, K/D/A e KDA, CS e
CS/min, dano causado/recebido, ouro, duração, visão e itens finais. O resumo e a
comparação com partidas anteriores usam apenas dados coletados. Campos ausentes
não são substituídos por valores inventados.

## Persistência

São adicionadas tabelas `lol_guilds`, `lol_players`, `lol_matches` e
`lol_deliveries` no **pro_lives.sqlite3** já usado pelo bot. As tabelas existentes
não são removidas ou substituídas. Preserve o arquivo no volume persistente da
hospedagem. PUUID, região, monitoramento ativo/inativo, partida atual, última
notificada e estados de entrega sobrevivem a reinícios.

## Testes e validação operacional

Resultado desta entrega: **240 testes aprovados, zero falhas**, sendo 50 testes
do tracker e 190 das funcionalidades existentes. A verificação estática dos novos
arquivos Python e `pip check` também passaram. Seis imagens oficiais foram
baixadas e validadas pela assinatura PNG; a prévia HTML usa essas imagens
embutidas e os mesmos renderizadores do comando de demonstração.

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Os testes do módulo estão em `tests/test_lol_tracker.py`. Usam SQLite temporário,
servidores HTTP locais para os clientes reais e mocks de Discord/Riot. O catálogo
em `tests/fixtures/lol_catalog.json` é uma captura de metadados oficiais do patch
16.22.1; todas as partidas e estatísticas de demonstração são **fictícias**.
`Mochila#bunny` no demo não comprova que essa conta foi localizada na Riot.

Nesta implementação, uma consulta externa real ao Data Dragon confirmou 173
campeões e 863 itens no patch 16.22.1. A configuração aplicada não declarou
RIOT_API_KEY nem autenticação Riot injetada pelo proxy, e a variável não estava
presente no processo. Portanto, Account/Spectator/Match não puderam ser validados
com credenciais reais e Mochila#bunny não foi consultada na Riot.

Nenhum destino do tracker estava configurado no ambiente; não foram enviadas
mensagens reais ao Discord. Após implantar, execute canal e teste para inspeção
visual das três mensagens. O teste demonstra a renderização; a operação completa
automática depende da chave Riot válida e do acesso aos endpoints oficiais.

## Arquivos da implementação

Criados:

- `cogs/lol_tracker.py`: comandos de prefixo, tarefa e ciclo de vida.
- `services/riot_service.py`: clientes Riot/Data Dragon, caches, limites e erros.
- `services/lol_tracker_repository.py`: persistência SQLite nas tabelas `lol_*`.
- `services/lol_tracker_service.py`: detecção, fases, enriquecimento e entregas.
- `services/lol_presentation.py`: builds heurísticas, embeds e demonstrações.
- `tests/test_lol_tracker.py`: 50 testes HTTP, banco, monitor, renderização e comandos.
- `tests/fixtures/lol_catalog.json`: metadados oficiais para testes isolados.
- `docs/lol_tracker.md`: configuração, comportamento e limitações.

Modificados: `bot.py` registra a extensão e `cogs/moderation.py` inclui o módulo
na ajuda geral. Nenhuma dependência de aplicação foi adicionada.
