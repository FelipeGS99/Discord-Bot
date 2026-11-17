# Canais privados por partida de futebol

Ative as ligas por servidor. Assim que uma partida aparecer ao vivo na BSD, o bot
cria um canal de texto como `spfc-x-pal`. Inicio, gols, intervalo, mudancas de
status e resultado final sao publicados nesse canal. O bot consulta a API a cada
minuto; a deteccao depende da atualizacao dos dados da BSD.

O canal e criado privado desde a primeira requisicao: `@everyone` nao pode
visualiza-lo; o cargo **Futebol** pode ver, conversar e consultar o historico. O
bot tem acesso proprio. Administradores continuam vendo o canal por regra do
Discord. As permissoes da categoria nao sao copiadas para tornar o canal publico.

O nome Futebol e procurado no servidor na primeira ativacao, sem diferenciar
maiusculas e minusculas. O ID e salvo: renomear o cargo depois nao rompe o vinculo.
Se nao houver um unico cargo com esse nome, informe explicitamente o cargo. Nunca
ha fallback para canal publico caso o cargo seja removido ou nao encontrado.

## Comandos

Exemplos com prefixo `?` (use o prefixo configurado no seu bot):

```text
?futebol ativar brasileirao
?futebol ativar libertadores
?futebol ativar sulamericana
?futebol ativar copadobrasil
?futebol prazo 60
?futebol status
?futebol parar brasileirao
```

Os grupos de cada competicao tambem aceitam `ativar`, `status` e `parar`:

```text
?brasileirao ativar
?libertadores ativar
?sulamericana ativar
?copadobrasil ativar
```

Para escolher categoria e/ou cargo na ativacao:

```text
?futebol ativar brasileirao "Jogos de futebol" @Futebol
?brasileirao ativar "Jogos de futebol" @Futebol
```

Use o nome ou ID de uma categoria existente, entre aspas se tiver espacos, e a
mencao ou ID do cargo. Na primeira ativacao sem categoria, o bot usa a categoria
do canal do comando; se nao houver, cria os canais na raiz do servidor. O bot nao
cria nem apaga categorias ou cargos. Cargo e categoria sao uma configuracao
compartilhada por todas as ligas do servidor. Mudar o cargo na ativacao atualiza
tambem as permissoes dos canais de partidas existentes; a categoria escolhida
vale para os proximos canais.

Somente o dono, administradores ou membros com `Gerenciar canais` podem ativar,
desativar ou alterar o prazo. Consultas de jogos e rodadas continuam disponiveis.
Os comandos de configuracao devem ser usados dentro de um servidor.

## Encerramento e recuperacao

- O prazo padrao e **60 minutos apos o primeiro encerramento confirmado** pela API.
  `futebol prazo <minutos>` aceita 1 a 1440 e recalcula tambem os prazos de canais
  que ja estao no periodo apos o jogo.
- Durante esse periodo o bot continua consultando detalhes e publicando correcoes
  de placar/status. Ausencia em `/live` nao significa que a partida terminou: o
  bot consulta o ID individual, inclusive para jogos que atravessam a meia-noite.
- Jogos cancelados, abandonados, adiados depois da criacao do canal ou encerrados
  administrativamente tambem iniciam o prazo. Estado desconhecido ou erro de API
  preserva o canal; nesses casos e preciso aguardar a confirmacao ou revisar o
  estado da partida. Se o jogo voltar a estar ao vivo antes da exclusao, o prazo
  e cancelado e comeca novamente no proximo encerramento.
- A exclusao acontece no primeiro ciclo apos vencer o prazo (normalmente ate um
  minuto depois). Falhas no Discord sao tentadas novamente. Se o bot estiver
  desligado, a limpeza pendente ocorre quando ele voltar.
- Desativar uma liga impede novos canais. Canais ja criados continuam recebendo
  atualizacoes e sao removidos no prazo normal. Apagar um canal manualmente e
  respeitado: a mesma partida nao gera outro canal.
- O estado e salvo em `football_channels_state.json`, ignorado pelo Git. Preserve
  esse arquivo no armazenamento persistente da hospedagem. Nao rode duas instancias
  simultaneas usando esse mesmo estado. IDs de canais, partidas, entregas e prazos
  sobrevivem a reinicios. Um identificador no topico permite recuperar criacoes
  interrompidas; nao remova esse identificador enquanto o bot gerencia o canal.
- A remocao de canais vencidos continua mesmo se a BSD estiver indisponivel.
  Somente canais registrados com o identificador da partida sao apagados.
- Se a liga for ativada com jogo ja em andamento, o canal sera criado na proxima
  consulta. Partidas apenas agendadas ou ja encerradas nao criam novos canais.

## Configuracao anterior

Os comandos `<liga> canal #placares` foram substituidos por `<liga> ativar`.
Reative as ligas desejadas em cada servidor. Arquivos antigos `*_state.json`
nao sao migrados automaticamente: eles nao definem o cargo de acesso necessario
para criar canais privados. Canais antigos de placares nao sao apagados.
Telegram e alertas de e-sports mantem suas configuracoes existentes.

## Verificacao

Os testes usam mocks do Discord, API simulada, relogio controlado e arquivos de
estado temporarios. Cobrem privacidade desde a criacao, falhas e reinicios,
identidade de canais, isolamento por servidor, deduplicacao de atualizacoes,
encerramento confirmado, troca de cargo e exclusao apos o prazo. Nenhum teste
cria ou apaga canais reais.
