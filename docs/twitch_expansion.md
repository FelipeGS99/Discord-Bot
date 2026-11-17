# Twitch: catálogo global de jogadores — 16/11/2026

Foram acrescentados **26 jogadores com conta Twitch identificada e consulta de
estado validada**, além de **três jogadores com links pendentes**. O catálogo
passou a **62 jogadores registrados**: **59 prontos para monitorar em 60 canais**
e três com uma conta pendente cada. Os 33 jogadores/34 canais anteriores foram
preservados integralmente, com os mesmos IDs, fontes, equipes, datas e status.
Nenhuma aplicação Twitch precisa ser cadastrada para o método público validado.

## Origem e escopo

A [página Mauro Garih](https://www.maurogarih.com/en/herramientas/streamers) e sua
[API pública](https://www.maurogarih.com/api/streamers) forneceram 29 contas
Twitch. Os links de live foram normalizados para o login canônico minúsculo,
sem usar caminhos `/videos` como ID. Não se geraram contas pelo nome do jogador.
Cada login foi consultado na Twitch para obter identidade numérica e estado.

O suporte aceita jogadores profissionais **de qualquer região** na Twitch.
A lista encontrada nesta fonte é principalmente europeia/LEC; isso não significa
cobertura completa mundial. Não foram inventados jogadores de outras regiões
para preencher a lista. São aceitas todas as cinco posições, normalizando
`JNG` para `JUNGLE` e `SUP` para `SUPPORT`.

Equipe e posição vieram do site indicado, sem exigir nova comprovação de
contrato. A equipe é a última informada pela fonte, não garantia de vínculo
atual. Oscarinin, Hylissang e Jopa estavam sem equipe informada; não foram
atribuídos a um clube por hipótese. O perfil de Hylissang declara uma pausa,
o que foi tratado como revisão e não prova de aposentadoria. `GLOBAL` marca
cadastros cuja liga atual não foi confirmada. Nos novos registros,
`competitive_status=unconfirmed`, `contract_status=unknown` e `division=null`
explicitam as lacunas, sem bloquear o monitoramento das contas identificadas.
A regra regional existente para SOOP/Huya/Douyu/Bilibili/CHZZK foi preservada.

## Contas cadastradas

“Pronto / offline” significa login e UID conferidos e consulta válida; não
significa que observamos o jogador iniciar uma live. “Pendente” é apenas um
link publicado pela fonte, sem titular identificado na consulta atual.

| Jogador | Equipe informada pela fonte | Posição | Canal Twitch | Resultado |
| --- | --- | --- | --- | --- |
| Oscarinin | Nao informado pela fonte | TOP | [oscarinin](https://www.twitch.tv/oscarinin) | Pronto / offline |
| BrokenBlade | G2 Esports | TOP | [brokenblade](https://www.twitch.tv/brokenblade) | Pronto / offline |
| Canna | Karmine Corp | TOP | [canna](https://www.twitch.tv/canna) | Pronto / offline |
| Myrwn | Movistar KOI | TOP | [myrwnn](https://www.twitch.tv/myrwnn) | Pronto / offline |
| Naak Nako | Team Vitality | TOP | [naaknako7](https://www.twitch.tv/naaknako7) | Pronto / offline |
| Razork | Fnatic | JUNGLE | [razorklol](https://www.twitch.tv/razorklol) | Pronto / offline |
| Humanoid | Team Vitality | MID | [humanoiidd](https://www.twitch.tv/humanoiidd) | Pendente: usuário não encontrado |
| Upset | Fnatic | ADC | [upsetger](https://www.twitch.tv/upsetger) | Pronto / offline |
| Mikyx | SK Gaming | SUPPORT | [m1kyx](https://www.twitch.tv/m1kyx) | Pronto / offline |
| SkewMond | G2 Esports | JUNGLE | [skewmond_lol](https://www.twitch.tv/skewmond_lol) | Pronto / offline |
| Caps | G2 Esports | MID | [caps](https://www.twitch.tv/caps) | Pronto / offline |
| Hans Sama | G2 Esports | ADC | [hanssama](https://www.twitch.tv/hanssama) | Pronto / offline |
| Jackies | GIANTX | MID | [jackissek](https://www.twitch.tv/jackissek) | Pendente: usuário não encontrado |
| Noah | GIANTX | ADC | [krnoah7](https://www.twitch.tv/krnoah7) | Pronto / offline |
| Yike | Karmine Corp | JUNGLE | [yikelol](https://www.twitch.tv/yikelol) | Pronto / offline |
| Caliste | Karmine Corp | ADC | [caliste_lol](https://www.twitch.tv/caliste_lol) | Pronto / offline |
| Targamas | Team BDS | SUPPORT | [targamas1](https://www.twitch.tv/targamas1) | Pronto / offline |
| Elyoya | Movistar KOI | JUNGLE | [elyoyalol](https://www.twitch.tv/elyoyalol) | Pronto / offline |
| Jojopyun | Movistar KOI | MID | [jojopyun](https://www.twitch.tv/jojopyun) | Pronto / offline |
| Supa | Movistar KOI | ADC | [supa_lol](https://www.twitch.tv/supa_lol) | Pronto / offline |
| Alvaro | Movistar KOI | SUPPORT | [alvaro710x](https://www.twitch.tv/alvaro710x) | Pronto / offline |
| Nuc | Shifters | MID | [nuclearintt](https://www.twitch.tv/nuclearintt) | Pendente: usuário não encontrado |
| Sheo | Team Heretics | JUNGLE | [sheo_lol](https://www.twitch.tv/sheo_lol) | Pronto / offline |
| Flakked | GIANTX | ADC | [getflakked](https://www.twitch.tv/getflakked) | Pronto / offline |
| Lyncas | Team Vitality | JUNGLE | [lyncaslol](https://www.twitch.tv/lyncaslol) | Pronto / offline |
| Carzzy | Team Vitality | ADC | [carzzy](https://www.twitch.tv/carzzy) | Pronto / offline |
| Hylissang | Nao informado pela fonte | SUPPORT | [hylissanglol](https://www.twitch.tv/hylissanglol) | Pronto / offline |
| Busio | Karmine Corp | SUPPORT | [busiolol](https://www.twitch.tv/busiolol) | Pronto / offline |
| Jopa | Nao informado pela fonte | ADC | [adcjopa](https://www.twitch.tv/adcjopa) | Pronto / offline |

**Humanoid (`humanoiidd`), Jackies (`jackissek`) e Nuc (`nuclearintt`)** retornaram
`user=null`. Isso não é offline: pode ser link antigo, renomeação, remoção ou
indisponibilidade da conta; a causa não foi determinada. Não foram inventados
substitutos nem atribuídos UIDs de outras pessoas. Permanecem no catálogo com
`monitoring_status=pending`, motivo e data da consulta; não entram nas consultas
nem nas contagens operacionais, mas aparecem em `?prolives jogadores` e
`?prolives status`. Não carregam `verified_at` como se tivessem sido confirmados.

## Consulta implementada e validação real

O cliente lê o identificador **público do site** no HTML de
`https://www.twitch.tv/`, mantendo cache por seis horas, e usa consultas HTTP
assíncronas de metadados em `https://gql.twitch.tv/gql`. São lotes de até 20
contas, solicitando `user.id`, `login`, `broadcastSettings.title` e
`stream { id type createdAt }`. Não há cookies, login de usuário, OAuth,
stream key, token de playback ou tentativa de contornar bloqueios.

O adaptador de produção foi executado com as 26 contas e um controle público:
**27 consultas de conta válidas**. As 26 contas de jogador estavam offline; o
controle público **illojuan**, fora do catálogo, retornou uma transmissão
online com ID de sessão, horário e título, reconhecidos pelo mesmo adaptador.
O controle não foi adicionado ao catálogo de jogadores.

Offline exige **usuário existente, UID igual ao cadastrado, login correto e
campo `stream` explicitamente nulo**. Online exige `stream.type=live`, ID de
sessão positivo, horário válido com fuso e título textual. Erros HTTP, desafios
HTML, erros GraphQL, campos ausentes, `user=null`, dono diferente e resposta
incompleta são desconhecidos, nunca offline. Replay `rerun` não gera alerta.

O ID de sessão da própria Twitch é usado na deduplicação SQLite já existente.
O UID do dono fica no catálogo para detectar se um login passou a identificar
outra conta. Tanto logins quanto UIDs duplicados entre contas são rejeitados.
Uma falha em uma conta não descarta resultados válidos das demais; uma falha
Twitch não suspende as outras plataformas. Lotes incompletos não fabricam
estados para contas ausentes. Consultas respeitam os timeouts, limite de uma
requisição por segundo por plataforma e tratamento de HTTP 429 já existentes.

Este é um endpoint **interno público do site**, sujeito a mudanças e bloqueios,
sem contrato de estabilidade de API pública. A alternativa oficial é a
[API Helix Get Streams](https://dev.twitch.tv/docs/api/reference/#get-streams),
que exige registro de aplicação e autenticação. Não se promete que o método
público dispense credenciais para sempre; se parar de funcionar, o monitor
registrará erro e preservará o último estado. Não há fallback para o booleano
“live” do site de terceiros nem inferência de offline por erro HTTP.

## Compatibilidade, comandos e testes

O mesmo ciclo de quatro minutos, configuração de canal, embeds e SQLite é
reutilizado. A primeira observação continua sendo referência sem aviso
retroativo. Revisões vencidas e situação contratual não excluem jogadores.
Não houve migração de banco, alteração de chaves antigas ou perda de histórico.

O comando `?prolives jogadores` agora inclui contas prontas e pendentes com
rótulos distintos. `?prolives status` mostra a cobertura operacional, contagem
de pendentes e respectivos motivos. O catálogo permite `twitch` para qualquer
liga/região; as plataformas anteriores seguem suas restrições regionais.

A suíte completa passou com **155 testes**, incluindo 13 novos testes Twitch:
identidade, online/offline reais reduzidos a fixtures, replay, conta inexistente,
resposta malformada, HTTP de erro, espera após falha, lotes e cache, regiões,
pendências visíveis, isolamento, transições, persistência e deduplicação após
reinicialização. A validação dos 33 jogadores/34 canais anteriores em datas
futuras também foi preservada. `git diff --check` passou.

Nenhum início natural de transmissão de jogador nem envio real ao Discord foi
observado nesta etapa. Os testes de transições/notificações são simulados.
Nenhum segredo foi exposto; não houve publicação no GitHub ou Square Cloud.
O [arquivo de evidências](twitch_expansion_evidence.json) guarda as identidades,
as URLs da fonte e os resultados mínimos necessários para revisão.
