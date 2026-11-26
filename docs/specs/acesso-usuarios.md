# Acesso de usuários: convite, esqueci minha senha e troca obrigatória

Especificação da frente `saira-acesso-usuarios` (25/11/2026). Backend em
`services/backend`, frontend em `services/frontend`.

## Problema

Hoje quem cria um usuário escolhe a senha dele e precisa entregá-la por fora
(e-mail, WhatsApp). Senha não deve trafegar por e-mail nem ser conhecida por
outra pessoa. A tela de login tinha "Esqueceu a senha?" que só abria um
`mailto:` para `suporte@saira.com`.

## Fluxos

### 1. Convite (primeiro acesso)

1. O administrador cria o usuário só com nome, e-mail, cargo e demais dados,
   **sem senha** (`POST /users/` sem `password`). O usuário nasce com
   `password_hash = NULL` (convite pendente) e o sistema envia o e-mail de
   convite.
2. Para um usuário que já existe (por exemplo, os criados à mão com senha
   provisória), o administrador usa `POST /users/{id}/invite`. Isso **revoga a
   senha atual** (`password_hash = NULL`), derruba as sessões abertas e manda o
   convite. Motivo: a senha provisória foi escolhida por outra pessoa; se ela
   continuasse valendo, quem a conhece entraria e definiria a senha no lugar do
   dono. O mesmo endpoint serve de "reenviar convite": cada envio invalida os
   links anteriores ainda não usados.
3. O e-mail traz o link `https://<painel>/definir-senha#token=<token>`. O token
   vai no fragmento (`#`), que o navegador não manda ao servidor: não aparece em
   log de nginx nem em cabeçalho `Referer`.
4. A página "Definir senha" lê o token, consulta `POST /auth/password/token`
   (mostra "Olá, Fulano" ou o motivo do erro) e envia a senha nova para
   `POST /auth/password/set`. Depois vai para o login com o e-mail preenchido.

Validade do convite: **48 h** (`ACCESS_INVITE_TTL_HOURS`).

### 2. Esqueci minha senha

1. Na tela de login, "Esqueceu a senha?" abre um campo de e-mail e chama
   `POST /auth/password/forgot`.
2. A resposta é **sempre** `202` com a mesma mensagem, exista ou não o e-mail,
   esteja o usuário ativo ou não. Não revela quem tem conta.
3. Se o e-mail é de um usuário ativo, sai o e-mail com o link
   `https://<painel>/definir-senha#token=<token>` (mesma página do convite).
4. Limite: 3 pedidos por e-mail por hora e 10 por IP por hora
   (`PASSWORD_FORGOT_MAX_PER_EMAIL_HOUR`, `PASSWORD_FORGOT_MAX_PER_IP_HOUR`).
   Passou do limite: a resposta continua `202` igual, mas nenhum e-mail sai
   (responder `429` só por e-mail revelaria que alguém pediu para aquele
   endereço). Por IP o excesso responde `429`, porque não revela nada sobre
   contas.

Validade do link de recuperação: **60 min** (`PASSWORD_RESET_TTL_MINUTES`).

### 3. Troca obrigatória no primeiro login

- Coluna `users.must_change_password`. Fica `true` quando um administrador
  define a senha de alguém (`POST /users/` com `password` ou `PATCH` com
  `password`): essa senha é provisória por definição.
- O login funciona e devolve o token, mas o backend responde `403` com
  `detail = "password_change_required"` em toda rota que exige login, exceto
  `GET /auth/me` e `POST /auth/password/change`. A regra fica no backend
  (`get_current_user`), não só no frontend, para ninguém pular a tela.
- O frontend, ao ver `must_change_password` no `/auth/me` (ou o `403` acima),
  leva a pessoa para "Trocar senha", que pede a senha atual e a nova.

### 4. Trocar senha logado

`POST /auth/password/change` com `current_password` e `new_password`. Senha
atual errada responde `400` (não `401`, que o frontend trata como sessão
vencida). Devolve um token novo, porque a troca derruba as sessões anteriores.

## Modelo de dados (migração `v3w4x5y6z7a8`)

Tabela nova `user_action_tokens`:

| coluna | tipo | nota |
|---|---|---|
| id | integer PK | |
| user_id | integer FK users.id ON DELETE CASCADE | índice |
| purpose | varchar(20) | `invite` ou `reset` |
| token_hash | varchar(64) único | SHA-256 do token, em hex |
| expires_at | timestamptz | |
| used_at | timestamptz nulo | preenchido ao consumir |
| created_at | timestamptz | |
| created_by_user_id | integer FK users.id ON DELETE SET NULL, nulo | quem convidou |
| request_ip | varchar(45) nulo | IP do pedido de recuperação |

Colunas novas em `users`:

- `password_hash` passa a aceitar `NULL` (convite pendente: não há senha que
  sirva no login).
- `must_change_password boolean NOT NULL DEFAULT false`.
- `token_version integer NOT NULL DEFAULT 0`: vai no JWT como `ver`; somar 1
  invalida todos os JWT emitidos antes (token sem `ver` conta como 0).
- `password_changed_at timestamptz NULL`: auditoria.

Sem backfill: usuários atuais ficam com `must_change_password = false` e
`token_version = 0`, e os JWT abertos continuam valendo.

## Rotas

Públicas (sem login; erros de token respondem `400`, nunca `401`):

| rota | corpo | resposta |
|---|---|---|
| `POST /auth/password/forgot` | `{email}` | `202 {message}` sempre |
| `POST /auth/password/token` | `{token}` | `200 {purpose, name, email, expires_at}` ou `400 {detail}` |
| `POST /auth/password/set` | `{token, password}` | `200 {message, email}` ou `400 {detail}` |

`detail` dos erros de token: `token_invalid` (não existe, adulterado ou
substituído por um mais novo), `token_expired`, `token_used`.

Com login:

| rota | quem | nota |
|---|---|---|
| `POST /auth/password/change` | qualquer logado | `{current_password, new_password}` → `{access_token, token_type}` |
| `POST /users/` | admin | `password` opcional; sem ela, cria com convite pendente e envia o convite (`send_invite`, padrão `true`) |
| `POST /users/{id}/invite` | admin | revoga a senha, derruba sessões, invalida links antigos e envia convite novo |

`UserResponse` ganha `must_change_password`, `invite_pending` e
`last_login_at`; `POST /users/` e `/invite` devolvem `invite_email_sent`.

Login: o corpo de `POST /auth/login` ganha `must_change_password`. Limite de
tentativas: 10 falhas por e-mail em 15 min (`LOGIN_MAX_FAILURES_PER_EMAIL`,
`LOGIN_FAILURE_WINDOW_MINUTES`) respondem `429` até a janela passar. Usuário
com convite pendente recebe o mesmo `401` de senha errada.

## Token

- `secrets.token_urlsafe(32)`: 256 bits aleatórios, 43 caracteres.
- No banco só o SHA-256. Hash rápido basta porque o token tem 256 bits de
  entropia (não dá para adivinhar por força bruta, ao contrário de senha).
- Uso único: consumir marca `used_at` dentro da mesma transação que grava a
  senha, com `UPDATE ... WHERE used_at IS NULL` para que dois cliques
  simultâneos não consumam duas vezes.
- Emitir um token novo apaga os pendentes do mesmo usuário e propósito. Definir
  ou trocar a senha apaga todos os pendentes do usuário (convite e
  recuperação).
- A validade é conferida no servidor, em UTC.

## E-mails

Pelo `email_service.send_email` (Resend), remetente `EMAIL_FROM` com o nome
`ACCESS_EMAIL_FROM_NAME` (padrão `SAÍRA`). Todos em português, HTML simples
mais versão texto, sem senha no corpo:

1. **Convite** — "Seu acesso ao SAÍRA": quem convidou, link, validade de 48 h.
2. **Recuperação** — "Redefinir sua senha do SAÍRA": link, validade de 60 min,
   "se não foi você, ignore".
3. **Senha alterada** — "Sua senha do SAÍRA foi alterada": data e hora; "se não
   foi você, fale com o administrador". Sai depois de `set` e `change`.

O endereço do painel nos links vem de `APP_PUBLIC_URL`; vazio usa
`REPORT_DASHBOARD_URL`, que já está certo no teste
(`https://test-saira.manaca.tech`) e na produção (`https://saira.manaca.tech`).
`WEB_APP_URL` não serve: na produção vale `http://localhost:3000`.

Envio que falha não derruba a rota: o convite fica gravado, a resposta traz
`invite_email_sent = false` e o administrador reenvia.

## Política de senha

Mínimo de 8 caracteres (mantido), máximo de 128, e recusa: senha igual ao
e-mail ou à parte antes do `@`, um só caractere repetido, e uma lista curta de
senhas óbvias (`12345678`, `senha123`, `saira123`...). Sem regra de "tem que ter
número e símbolo": a NIST SP 800-63B recomenda comprimento e lista de bloqueio
em vez de composição, que só gera `Senha@123`. O mínimo segue 8 porque é o que
os usuários atuais já têm.

## Sessões

- Definir ou trocar a senha soma 1 em `token_version`: todo JWT anterior deixa
  de valer (o `get_current_user` compara `ver`).
- O convite para usuário existente também soma 1 (a senha provisória e quem
  entrou com ela saem juntos).
- Desativar o usuário já bloqueava (`is_active`).

## O que ficou de fora (e por quê)

- Bloqueio de conta por tentativas: o limite por e-mail é temporário (janela de
  15 min) para não virar negação de serviço contra um usuário.
- Segundo fator: fora do escopo; o login do Conecta Recife é o caminho de
  autenticação forte para a prefeitura.
- Expiração periódica de senha: desaconselhada pela NIST.
