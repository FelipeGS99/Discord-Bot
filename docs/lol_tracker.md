# Tigrão — LoL Live Tracker

`?loltrack seguir Nome#TAG` ativa uma conta (BR1) no servidor. Quando ela entra
em uma partida, o bot cria um **canal privado com o nick do jogador**, por exemplo
`mochila`. Live Match, build e relatórios desse jogador ficam nesse canal.

Partidas seguidas reutilizam o mesmo canal. Ele é apagado **uma hora após o último
encerramento confirmado, sem uma nova partida**. O prazo não corre enquanto o
jogador está em partida. Uma nova partida cancela o prazo anterior e seu fim
inicia outra hora. A duração não é uma hora desde a criação: um jogador pode
jogar várias partidas durante a mesma sessão de canal.

## Privacidade e permissões

Crie um único cargo chamado **LOL** em cada servidor e atribua-o a quem deve ter
acesso. O bot não distribui o cargo. A busca inicial ignora maiúsculas/minúsculas;
o ID é salvo, então renomear o cargo depois não rompe o vínculo.

Desde a requisição de criação, o canal nega Ver canal para `@everyone`, permite
Ver/Enviar/Ler histórico ao cargo LOL e dá acesso próprio ao bot. Não copia as
permissões públicas da categoria. Antes das entregas, verifica e corrige os
overwrites. **Administradores continuam tendo acesso por regra do Discord.**
Sem o cargo válido, não há fallback para canal público.

Um jogador tem seu próprio canal por servidor. Dois jogadores seguidos na mesma
partida recebem seus Live Matches, builds e relatórios nos respectivos canais,
sem misturar o acompanhamento de um com o do outro. Nomes iguais podem gerar
canais de mesmo nome, mas cada conta é vinculada pelo PUUID/ID interno.

## Configuração e comandos

1. Vincule a chave oficial Riot à variável **RIOT_API_KEY** no processo do bot,
   usando o cofre/configuração do servidor. Não coloque a chave no Git ou no chat.
   Reinicie após mudar o vínculo; chaves de desenvolvimento expiram.
2. Permita HTTPS com TLS verificado a `americas.api.riotgames.com`,
   `br1.api.riotgames.com` e `ddragon.leagueoflegends.com`. Clientes respeitam proxy
   e CA do ambiente (`trust_env=True`).
3. Crie o cargo **LOL** e execute `?loltrack seguir Mochila#bunny`.

| Comando | Comportamento |
|---|---|
| `?loltrack seguir Nome#TAG` | Resolve a conta oficial, persiste PUUID e passa a acompanhar automaticamente. O primeiro canal só nasce quando a partida é detectada. |
| `?loltrack deixar Nome#TAG` | Para somente aquela conta, cancela suas notificações pendentes e agenda a limpeza do canal em uma hora. |
| `?loltrack categoria "League of Legends"` | Escolhe uma categoria existente para os próximos canais. |
| `?loltrack categoria` | Cria os próximos canais na raiz do servidor. |
| `?loltrack lista` | Contas ativas/inativas e estado da última consulta. |
| `?loltrack status` | Tarefa, quantidade de jogadores, canais abertos, cargo, saúde Riot e última verificação. |
| `?loltrack teste` | Cria/reutiliza `teste-mochila`, privado para LOL, e envia três exemplos **MODO TESTE**. O canal de teste expira após uma hora. |

Na primeira ativação, sem categoria configurada, usa-se a categoria do comando
quando ela existir; caso contrário, a raiz do servidor. Alterar a categoria vale
para novos canais e não desloca uma sessão já em uso. O bot não cria categorias
nem cargos. Cadastros, categoria e teste exigem dono, Administrador ou Gerenciar
servidor. O bot precisa gerenciar canais, enviar embeds e ler histórico.

O antigo `?loltrack canal #referencia` continua aceito apenas para usar a categoria
desse canal como referência. **Não envia alertas para esse canal fixo.** Nenhum ID
de canal precisa ser passado para começar a seguir uma conta.

Os exemplos usam `?`; o bot respeita `BOT_PREFIX`. Os comandos de campeonatos
profissionais continuam em `?lol`, incluindo `lol canal`. Não há slash commands.
Nenhum programa/League Client API/agente é instalado no computador dos jogadores.

## Demonstração visual

```text
?loltrack teste
```

O cargo LOL precisa existir, mas a demonstração **não exige chave Riot nem partida
ativa**. A conexão com Data Dragon é necessária para itens e imagens oficiais.
Cria-se um canal separado do acompanhamento real, chamado `teste-mochila`:

1. Live Match com equipes, campeões e exemplos de estatísticas históricas.
2. Build heurística com itens iniciais, botas, principais e imagens.
3. Relatório pós-partida fictício.

Tudo está marcado MODO TESTE e usa os mesmos renderizadores das notificações reais.
O comando responde com links das mensagens. Há cooldown de 60 segundos por
servidor; testes repetidos dentro da hora reutilizam o canal e renovam o prazo.
A conta demonstrativa não é cadastrada para monitoramento real.

## Monitoramento, recuperação e exclusão

- A tarefa inicia com o bot, espera o Discord ficar pronto e carrega os cadastros
  do SQLite. Não são necessários comandos para detectar cada partida.
- O ciclo é de aproximadamente 60 segundos, ajustado ao volume e às cotas Riot.
  Live Match é enviado antes das consultas históricas e enriquecido por edição.
- Spectator-V5 consulta PUUID. `404` significa ausência de partida; falha de rede,
  autenticação ou cota é estado desconhecido e não equivale a estar fora de jogo.
- Match-V5 confirma o resultado do ID exato, inclusive quando publicado com atraso
  ou quando o jogador já está em outra partida. Um relatório atrasado do jogo
  anterior não inicia a exclusão de um canal que já tem nova partida ativa.
- Antes de limpar um canal de jogador ainda seguido, o monitor faz a consulta
  atual de Spectator. Nova partida cancela a exclusão; consulta que falhou ou
  jogador ainda não verificado preserva o canal. Resultado/entrega pendente também
  pode adiar a limpeza. O canal só expira quando o estado é seguro para removê-lo.
- Remoção ocorre no primeiro ciclo após o prazo, não em um cronômetro desconectado
  do monitor. Se o bot estava desligado, recupera o prazo e confirma o estado
  antes de limpar. Sob cota ou falhas, a exclusão pode demorar mais de uma hora.
- Apagar um canal manualmente é respeitado: ele não é recriado para o mesmo jogo;
  uma nova partida pode criar uma nova sessão. O bot só apaga canais registrados
  cujo tópico contém o identificador de propriedade esperado. Não remova esse
  identificador enquanto o bot gerencia o canal.
- A intenção de criação é persistida antes da requisição Discord. Se a criação
  tiver funcionado mas a resposta/gravação tiver sido interrompida, o identificador
  no tópico recupera o mesmo canal em vez de criar duplicatas.
- Canais de demonstração ou de contas cujo acompanhamento foi interrompido podem
  ser limpos sem consultar a Riot. Falhas do Discord são tentadas no ciclo seguinte.
- Entregas são confirmadas somente após envio. Marcadores nos embeds recuperam a
  janela entre enviar e confirmar no banco nas últimas **100 mensagens** do canal.
  Essa recuperação não garante exatamente uma entrega se a mensagem saiu dessa
  janela ou o histórico foi apagado. Preserve Ler histórico e use uma instância.

HTTP 401/403 informa chave inválida/expirada/sem autorização e aplica pausa.
HTTP 429 respeita Retry-After; cotas e contagens ajustam o espaçamento global.
O intervalo inicial é 1,25 s por requisição, com até três tentativas para 5xx/rede,
backoff e timeouts. Caches reduzem chamadas repetidas entre jogadores/servidores.

## Dados, builds e apresentação

Live Match mostra os dez campeões, equipes e identidades fornecidas oficialmente,
modo e horário/duração disponíveis. Elo, WR acumulado da fila, KDA recente
(até cinco jogos) e WR do campeão (em até 20 jogos da fila) são apresentados
separadamente, com V/D e amostra. Maestria é consultada quando disponível.
São **estatísticas históricas**,
com amostra explícita; a partida atual é excluída da comparação. Identidades
omitidas pelo jogo não são resolvidas para desanonimizar outros participantes.
Spectator não fornece kills, ouro e inventário ao vivo; o módulo não os inventa.
O enriquecimento inicial pode atravessar mais de uma janela de rate limit.

As builds agora usam observações oficiais da Match-V5 e timelines, separadas por
campeão, posição, fila, mapa e patch. A lista fixa de itens por classe foi removida.
O núcleo exige 20 observações e cinco ocorrências de uma ordem confirmada por
timeline; sem isso, o card sinaliza dados insuficientes. A amostra local não é o
meta global. Data Dragon valida IDs/nomes/imagens e disponibilidade, nunca taxas
de vitória. Não há runas nem scraping de OP.GG/U.GG/Lolalytics. Detalhes, fontes,
limites e investigação de Yunara estão em [lol_build_sources.md](lol_build_sources.md).

O pós-partida usa Match-V5 para vitória/derrota, campeão, K/D/A e KDA, CS/CS-min,
dano causado/recebido, ouro, duração, visão e itens finais. Resumo e comparação
usam somente dados coletados; campos ausentes são explicitamente indisponíveis.
O topo aprovado foi preservado; a seção ANÁLISE DE DESEMPENHO agora separa
participação percentual nos abates da equipe, indicadores, comparação e leitura.

## Persistência e migração

São usadas tabelas `lol_*` no **pro_lives.sqlite3** existente, sem remover tabelas
ou dados de outras funcionalidades. `lol_channel_config` guarda cargo/categoria e
`lol_player_channels` guarda canal, geração de sessão, último jogo e prazo. As
transações SQLite rodam em threads. `lol_build_samples` mantém observações
estatísticas anônimas separadas, sem nomes ou PUUIDs, e um cache limitado por data. Preserve esse banco no armazenamento
persistente da hospedagem e evite duas instâncias simultâneas.

Configurações antigas de canal fixo não são usadas para notificações. Após atualizar
uma instalação anterior do tracker, execute `loltrack categoria` ou volte a usar
`loltrack seguir Nome#TAG` para ativar o vínculo ao cargo LOL. Cadastros e históricos
anteriores são preservados; os canais antigos não são apagados.

## Arquivos e validação

- `cogs/lol_tracker.py`: comandos de prefixo e tarefa.
- `services/riot_service.py`: clientes oficiais, caches e cotas.
- `services/lol_tracker_repository.py`: persistência SQLite.
- `services/lol_channel_service.py`: canais privados por jogador e ciclo de vida.
- `services/lol_tracker_service.py`: detecção, enriquecimento e entregas.
- `services/lol_presentation.py`: builds, embeds e demonstrações.
- `tests/test_lol_tracker.py`, `tests/test_lol_channels.py` e
  `tests/fixtures/lol_catalog.json`: testes com SQLite temporário, HTTP local,
  Discord/Riot simulados e relógio controlado.
- `bot.py` registra a extensão; `cogs/moderation.py` inclui a ajuda.

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Validação anterior de canais privados: **268 testes aprovados, zero falhas**, incluindo os
testes de sessões privadas, partidas em sequência e exclusão segura. A análise
estática dos arquivos alterados, `git diff --check` e `pip check` passaram.

A consulta externa real ao Data Dragon confirmou o patch 16.22.1, 173 campeões,
863 itens e seis imagens PNG. Após disponibilizar RIOT_API_KEY no ambiente,
Mochila#bunny foi consultada na Riot e foram validados conta, histórico, elo,
maestria, timeline e contagens de WR. A auditoria de WR está documentada abaixo.
Nenhum canal real foi criado/apagado e nenhuma mensagem real foi enviada:
o ciclo de vida e os envios foram simulados. As demonstrações usam dados
fictícios explicitamente identificados.

A revisão visual e do sistema de builds é documentada em `docs/lol_build_sources.md`.

A origem e o cálculo de cada WR, com auditoria real, estão em `docs/lol_win_rates.md`.
