# Mensagens do Tigrão no Discord

As respostas administrativas e de ajuda usam cartões com título, texto em português
do Brasil e identificação da funcionalidade no rodapé. Confirmações extensas
separam as informações em campos, como jogador, acesso ao canal e prazo de exclusão.

O padrão de `services/discord_messages.py` oferece quatro tons: informação (azul),
confirmação (verde), atenção (amarelo) e erro (vermelho). Os títulos e o texto também
explicam o resultado, sem depender apenas da cor. Listas e ajuda extensas são
paginadas respeitando os limites de mensagens, descrições e campos do Discord.

O envio mantém `delete_after` quando solicitado e desativa menções por padrão.
Se o bot puder enviar mensagens, mas não inserir embeds, a resposta usa texto
formatado com o mesmo conteúdo. Não é necessário ampliar permissões para receber
as respostas administrativas.

## Cobertura

- Futebol: ajuda, configuração, status, consulta de jogos e cartões automáticos do
  Brasileirão, Libertadores, Sul-Americana e Copa do Brasil.
- E-sports: ajuda, ativação, status, calendário e alertas de LoL, CS2 e Valorant.
- LoL Tracker: acompanhamento, categoria, lista, status, demonstração e erros de
  validação; rótulos e acentuação dos relatórios e análises foram revisados.
- Lives profissionais: configuração, cobertura, revisão de contas, listagem e alertas.
- Notícias do GE: configuração, status, erros e cartões com link para a notícia.
- Forca: instruções, andamento, palpites, validações e encerramento da partida.
- Moderação: ajuda geral organizada por área, validações e confirmações.
- Voz/TTS: fila, validações e falhas de reprodução, com orientações para o usuário.
- IA: tom profissional, cordial e direto na configuração distribuída, com avisos
  revisados. As respostas da conversa continuam em texto, inclusive para reprodução
  por voz; configurações personalizadas de prompt continuam aceitas.

O texto editorial recebido de fontes externas e os dados das partidas são
preservados. O Telegram não envia mensagens ao Discord e não recebe alteração
de comportamento nesta revisão. Marcadores de entrega e deduplicação do tracker
permanecem intactos, assim como permissões, comandos e regras das integrações.

Falhas de provedores recebem uma orientação pública curta. Os detalhes técnicos
ficam nos logs, sem copiar exceções, caminhos locais ou nomes de variáveis de
credenciais para as respostas comuns do chat.

## Validação

Os testes de apresentação exercitam a ajuda das funcionalidades, o prefixo
personalizado, a paginação de conteúdo longo, menções desativadas, a resposta sem
permissão de embeds, a preservação dos marcadores de entrega e o tratamento de
falhas de provedores. São usadas mensagens simuladas, sem enviar mensagens reais
ao Discord ou Telegram e sem executar moderação real.

Resultado da suíte completa: **351 testes aprovados, nenhuma falha**.
Ruff (`F`) e `git diff --check` também foram aprovados.
