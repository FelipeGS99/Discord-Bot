# SOOP: diagnóstico, correção e validação

> Atualização de política: prazos de verificação agora geram avisos e mantêm
> os 33 jogadores/34 canais. Referências abaixo a exclusão automática por
> vencimento descrevem o comportamento anterior. Veja a
> [regra atual de status competitivo e revisão](pro_lives.md#validade-e-status-competitivo).

> Registro histórico da etapa anterior, com dez jogadores. O estado atual e
> os 23 novos jogadores estão na [ampliação do catálogo](streamers_expansion.md).

Verificação externa em **16/11/2026, 12:28:48 de Brasília (15:28:48 UTC)**.
Nenhum deploy, publicação ou envio de mensagem real ao Discord foi realizado.

## Causa das consultas inconclusivas

O endpoint de player já respondia corretamente: no [JavaScript público da SOOP](https://static.sooplive.com/asset/app/liveplayer/player/dist/LivePlayer.js?_=202610201100),
o método `_validateBroadByAPI` interpreta `case 0` como `방송 중이지 않습니다.`
(não está transmitindo), com o código de interface `not_broading`.

O adaptador antigo lançava erro para **qualquer** `RESULT=0`. Essa cautela tinha
um motivo: uma conta inexistente também retorna HTTP 200 e `RESULT=0`. Portanto,
simplesmente trocar todo zero por offline produziria falsos encerramentos.
Faltava uma consulta independente para confirmar existência e identidade.

Foi comparado o POST original (`mode=landing`, sem BNO) com o formato atual do
player (`mode=live`, query `bjid` e formulário `bid`). Ambos reconheceram a mesma
transmissão de controle online. O modo antigo não foi identificado como a causa
do zero: o problema principal era a interpretação sem validação da estação.
O novo pedido segue o formato atual do cliente público, sem precisar descobrir
BNO antecipadamente, efetuar login, reproduzir mídia ou abrir navegador.

## Como a integração decide o estado

1. GET `https://api-channel.sooplive.com/v1.1/channel/{id}/station`.
   Exige objeto `station`, `userId` igual ao solicitado, `stationNo` inteiro
   positivo e nome de usuário não vazio. Metadados antigos, como `broadStart`,
   não são usados para deduzir que há uma live atual.
2. POST `https://live.sooplive.com/afreeca/player_live_api.php?bjid={id}`,
   com `bid`, `type=live`, `mode=live`, `player_type=html5`, `stream_type=common`,
   `quality=HD`, `from_api=0` e `bno` vazio.
3. Com estação confirmada, `CHANNEL.RESULT=0` é offline. `BNO` ativo contraditório
   ou `BJID` diferente mantém a consulta inconclusiva.
4. Online exige `RESULT=1`, `BJID` correspondente, `BNO` positivo e título string.
   O BNO é a identidade da transmissão e alimenta a deduplicação existente.
5. Códigos de restrição, payload inesperado, falha de identidade, timeout e erros
   HTTP são **desconhecidos**, nunca convertidos em offline.

Foi corrigido também o tratamento de 404 na SOOP: uma estação inexistente não
coloca todos os jogadores em espera. A validação externa incluiu uma conta
inexistente junto das contas válidas para conferir esse isolamento.

O transporte continua assíncrono, com proxy/CA herdados, TLS verificado, timeout
de 12 segundos, quatro requisições simultâneas no máximo e intervalo mínimo de
um segundo por plataforma. SOOP faz duas requisições por conta/ciclo: oito
requisições para os quatro jogadores, a cada quatro minutos. 429 e erros de
serviço preservam a espera e não falsificam uma mudança de estado.

## Validação contra a plataforma real

| Alvo | Identidade da estação | Estado reconhecido | Sessão |
| --- | --- | --- | --- |
| Kiin — `rldls5656` | Confirmada | Offline | Sem sessão ativa |
| Canyon — `rjsqn0618` | Confirmada | Offline | Sem sessão ativa |
| Chovy — `wlgnsdl0303` | Confirmada | Offline | Sem sessão ativa |
| Duro — `jmg3495` | Confirmada | Offline | Sem sessão ativa |
| Controle público — `dongwon1118` | Confirmada | Online | `298640685` |
| Controle inexistente | Não confirmada; HTTP 404 | Desconhecido | Nenhuma inferência |

O controle online foi descoberto no diretório público
`https://api.m.sooplive.com/broad/a/items`. A consulta de player retornou o mesmo
BNO e usuário informados no diretório, além do título. Esse controle serve
exclusivamente para validar o protocolo: **não é cadastro de jogador e não foi
adicionado ao catálogo**. Campos públicos mínimos das respostas online/offline
foram preservados em `tests/fixtures/soop_status.json`; URLs de acesso à mídia,
cookies, tokens e respostas completas do player não foram incluídos.

Resultado: **4 jogadores SOOP prontos para monitoramento**, elevando o catálogo
atual a **10 jogadores com consulta validada**, contando os seis Huya anteriores.
As regras de validade dos elencos continuam valendo, sem renovação automática
das datas ou alteração das associações.

## Testes automatizados

Os testes SOOP cobrem respostas reais reduzidas a fixtures, identidade inválida,
códigos de restrição, HTTP 200 sem estado válido, BNO inválido ou contraditório,
GET/POST e parâmetros, 404 por conta, indisponibilidade do serviço e espera.
Resultado executado: **13 testes SOOP e 122 testes na suíte completa passaram**.
O carregamento/descarregamento de todas as extensões continua coberto pela suíte;
`git diff --check` também passou.

A sequência de notificações é exercitada pelo parser e monitor reais, SQLite
temporário e Cog de entrega, com **Discord simulado**: offline → online,
repetição da mesma sessão, erro durante live, recuperação/reinício, encerramento,
reaparecimento do mesmo BNO e novo BNO. Confere conteúdo do embed, persistência,
nova tentativa de envio e ausência de duplicações. O primeiro estado online
continua sendo referência, sem notificação retroativa. O encerramento é gravado
como offline; os embeds continuam sendo enviados apenas no início de live.

```bash
DISCORD_TOKEN=offline-test-only PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B -m unittest discover -s tests -v
```

## Limites e alternativas

- Não foi observado início ou encerramento natural de live de um dos quatro
  jogadores durante a execução. Online foi validado com o controle real;
  transições e notificações foram validadas por testes simulados, não por uma
  mensagem enviada em um servidor real.
- Os endpoints são usados pelo site, sem garantia pública de estabilidade.
  Mudanças de formato falham de forma explícita. O novo host
  `api-channel.sooplive.com` e `live.sooplive.com` precisam ser permitidos em
  ambientes com lista restrita de saída.
- Não houve bloqueio externo dos quatro canais neste teste. Futuro 403/429,
  restrição regional/etária ou necessidade de autenticação mantém o último
  estado válido, sem fabricar encerramento. Conferir política de rede e
  mensagem/código do serviço antes de atribuir a causa a credenciais.
- Uma integração oficial autorizada pela SOOP ou uma sessão de consulta
  autenticada, se exigida e autorizada pelo provedor, são alternativas para
  restrições futuras. Não foi implementado contorno de desafios ou restrições.
- O intervalo de quatro minutos pode perder transmissões mais curtas que um
  ciclo. Caiu exatamente entre envio ao Discord e confirmação no SQLite ainda
  pode duplicar um aviso, conforme a limitação transacional já documentada.
- O cliente Discord mantém a configuração de rede existente; esta correção não
  faz deploy, não inicia o bot permanentemente e não configura canal de destino.
