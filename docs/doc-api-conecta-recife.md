# Projeto SAÍRA
## Documentação da API — Integração Conecta Recife

---

## SUMÁRIO

1. Visão Executiva
2. Contexto da Integração
3. Fluxo de Autenticação Federada
4. Referência de Endpoints
5. Modelo de Dados do Usuário Federado
6. Configuração do Ambiente
7. Segurança
8. Checklist de Homologação

---

## 1. Visão Executiva

O SAÍRA implementa autenticação federada com o Conecta Recife Login, o sistema de identidade centralizado da Prefeitura do Recife. Esta integração permite que agentes e fiscais da Prefeitura acessem o SAÍRA utilizando as mesmas credenciais institucionais já conhecidas, eliminando a necessidade de uma conta separada para o sistema.

A abordagem adotada é híbrida: o login local por e-mail e senha é preservado em paralelo, garantindo acesso contínuo para usuários internos e para cenários de contingência. A ativação da integração com o Conecta é controlada por variáveis de ambiente, permitindo rollout gradual e homologação controlada por ambiente.

O módulo de integração está disponível sob o prefixo `/api/v1/integrations/conecta` e cobre o fluxo completo de autenticação federada, incluindo geração da URL de login, processamento do callback, emissão de sessão, logout federado e revogação de dados pessoais conforme os requisitos da Carta de Serviços do Conecta Labs.

---

## 2. Contexto da Integração

### 2.1 O Protocolo OIDC

A integração utiliza o OpenID Connect (OIDC), um protocolo de identidade construído sobre o OAuth 2.0. O OIDC permite que o SAÍRA autentique usuários por meio de um provedor de identidade externo — neste caso, o Conecta Recife — sem nunca ter acesso direto às senhas institucionais. O protocolo garante que apenas o provedor de identidade valida as credenciais do usuário; o SAÍRA recebe apenas uma declaração verificada de identidade na forma de um ID Token assinado.

O fluxo implementado é o **Authorization Code Flow**, o mecanismo mais seguro definido pelo padrão OIDC para aplicações web com componente servidor. Neste modelo, o código de autorização é trocado por tokens exclusivamente no backend, nunca expondo credenciais ou tokens sensíveis ao navegador do usuário.

### 2.2 Modelo de Autenticação Híbrida

O SAÍRA opera em modo de autenticação híbrida, controlado por duas flags independentes de ambiente:

- **`ENABLE_LOCAL_LOGIN`**: quando `true`, o endpoint `/auth/login` aceita autenticação por e-mail e senha local, mantendo o acesso para usuários internos.
- **`ENABLE_CONECTA_LOGIN`**: quando `true`, os endpoints de integração com o Conecta ficam ativos e o botão "Entrar com Conecta Recife" é exibido na tela de login do frontend.

Esta separação permite que ambos os modos coexistam durante a fase de homologação, sem risco de indisponibilidade para usuários já cadastrados localmente. Usuários federados — autenticados via Conecta — são identificados pelo campo `auth_provider = "conecta"` e têm sua identidade vinculada pelo campo `external_subject`, que armazena o identificador único (`sub`) emitido pelo provedor OIDC.

---

## 3. Fluxo de Autenticação Federada

### 3.1 Etapas do Fluxo

A autenticação federada ocorre em quatro etapas principais, orquestradas entre o frontend React, o backend FastAPI e o servidor de identidade do Conecta Recife.

**Etapa 1 — Solicitação da URL de login**

O frontend chama `GET /integrations/conecta/login-url`. O backend gera um parâmetro `state` criptograficamente seguro (proteção anti-CSRF), monta a URL de autorização do Conecta com os campos `response_type=code`, `client_id`, `redirect_uri` e `scope=openid profile email`, e retorna ambos ao frontend. O frontend então redireciona o navegador do usuário para a URL de autorização do Conecta Recife.

**Etapa 2 — Autenticação no Conecta Recife**

O usuário realiza o login no portal do Conecta Recife com suas credenciais institucionais. Após a autenticação bem-sucedida, o Conecta redireciona o navegador para a `redirect_uri` previamente cadastrada, acrescentando os parâmetros `code` (código de autorização temporário de uso único) e `state` na URL de retorno.

**Etapa 3 — Callback e emissão do ticket interno**

O frontend encaminha a requisição de callback ao backend via `GET /integrations/conecta/callback?code=...&state=...`. O backend valida o `state` para garantir a integridade do fluxo, troca o `code` junto ao Conecta por um `id_token` (que contém os dados verificados de identidade do usuário) e por um `access_token`. Os dados do usuário — nome, e-mail e identificador único `sub` — são extraídos do `id_token`. O backend cria ou atualiza o registro do usuário no banco de dados do SAÍRA e emite um ticket interno temporário de uso único. Este ticket é retornado ao frontend.

**Etapa 4 — Troca do ticket por sessão SAÍRA**

O frontend apresenta o ticket ao backend via `POST /integrations/conecta/exchange-ticket`. O backend valida e descarta o ticket, emitindo um JWT de sessão do SAÍRA com o mesmo formato utilizado pelo login local. A partir deste momento, o frontend opera com um JWT SAÍRA padrão, sem nenhuma distinção de origem da autenticação nas chamadas subsequentes à API.

### 3.2 Diagrama do Fluxo

```
Usuário         Frontend React      Backend SAÍRA       Conecta Recife
   |                 |                    |                    |
   |-- clica ------->|                    |                    |
   | "Entrar com     |-- GET /login-url ->|                    |
   |  Conecta"       |<-- {url, state} ---|                    |
   |                 |--- redireciona o navegador para o Conecta -->
   |                                                           |
   |<----------- login institucional no Conecta Recife -------|
   |                                                           |
   |                 |<---- redirect com ?code&state ----------|
   |                 |-- GET /callback?code&state ->           |
   |                 |                    |-- troca code ----->|
   |                 |                    |<-- id_token -------|
   |                 |                    |-- cria/atualiza usuário no banco
   |                 |<-- { ticket } -----|                    |
   |                 |-- POST /exchange-ticket ->              |
   |                 |<-- { access_token (JWT SAÍRA) } --------|
   |                 |-- usa JWT para todas as chamadas da API  |
```

---

## 4. Referência de Endpoints

**Prefixo base:** `/api/v1`

Todos os endpoints desta seção requerem que a variável de ambiente `ENABLE_CONECTA_LOGIN=true` esteja configurada no serviço backend. Endpoints não disponíveis retornam `HTTP 503 Service Unavailable`.

---

### 4.1 GET /integrations/conecta/login-url

Gera a URL de autorização do Conecta Recife e um token de estado para proteção CSRF. Este é o primeiro endpoint chamado no fluxo de autenticação federada.

**Autenticação:** não requerida.

**Parâmetros de query:** nenhum.

**Resposta (200 OK):**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `authorization_url` | string | URL completa do Conecta Recife para redirecionamento do usuário |
| `state` | string | Token gerado pelo backend; deve ser armazenado pelo frontend e verificado no callback |

**Exemplo de resposta:**

```json
{
  "authorization_url": "https://conecta.recife.pe.gov.br/auth/realms/recife/protocol/openid-connect/auth?response_type=code&client_id=saira&redirect_uri=https%3A%2F%2Fsaira.recife.pe.gov.br%2Fauth%2Fcallback&state=abc123xyz&scope=openid+profile+email",
  "state": "abc123xyz"
}
```

---

### 4.2 GET /integrations/conecta/callback

Recebe o código de autorização retornado pelo Conecta Recife após a autenticação do usuário. Realiza a troca do código por tokens OIDC, cria ou sincroniza o registro do usuário no banco de dados e emite um ticket interno temporário.

**Autenticação:** não requerida.

**Parâmetros de query:**

| Parâmetro | Tipo | Obrigatório | Descrição |
|-----------|------|-------------|-----------|
| `code` | string | sim | Código de autorização emitido pelo Conecta Recife |
| `state` | string | sim | Token de estado para validação CSRF; deve corresponder ao emitido em `/login-url` |

**Comportamento:**

O backend valida o `state` recebido, realiza a troca do `code` por `id_token` e `access_token` junto ao endpoint de token do Conecta, extrai os campos `sub`, `name` e `email` do `id_token`, e localiza o usuário pelo `external_subject`. Caso o usuário não exista, um novo registro é criado com `auth_provider = "conecta"`. Caso já exista, nome e e-mail são atualizados. Um ticket interno de uso único com validade curta é gerado e retornado.

**Resposta (200 OK):**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `ticket` | string | Ticket temporário para troca por JWT SAÍRA no endpoint `/exchange-ticket` |
| `user_id` | integer | ID do usuário no banco de dados SAÍRA |

**Erros possíveis:**

| Código | Descrição |
|--------|-----------|
| 400 | `state` inválido ou ausente — possível tentativa de CSRF |
| 401 | Falha na troca do código com o Conecta Recife |
| 503 | Integração desabilitada por configuração de ambiente |

---

### 4.3 POST /integrations/conecta/exchange-ticket

Troca um ticket temporário, obtido no callback, por um JWT de sessão do SAÍRA. Este é o último passo do fluxo federado antes de o frontend operar normalmente com o token de sessão.

**Autenticação:** não requerida.

**Corpo da requisição (JSON):**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `ticket` | string | sim | Ticket emitido pelo endpoint `/callback` |

**Comportamento:**

O backend valida a existência e validade do ticket, o descarta para prevenir reuso e emite um JWT de sessão SAÍRA com expiração de 30 minutos, idêntico ao gerado pelo login local.

**Resposta (200 OK):**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `access_token` | string | JWT de sessão do SAÍRA |
| `token_type` | string | Sempre `"bearer"` |

**Erros possíveis:**

| Código | Descrição |
|--------|-----------|
| 400 | Ticket inválido, expirado ou já utilizado |
| 404 | Ticket não encontrado |

---

### 4.4 GET /integrations/conecta/logout-url

Gera a URL de logout federado do Conecta Recife. Ao redirecionar o usuário para esta URL, a sessão é encerrada tanto no provedor de identidade quanto no SAÍRA.

**Autenticação:** requerida (Bearer JWT SAÍRA no cabeçalho `Authorization`).

**Parâmetros de query:** nenhum.

**Resposta (200 OK):**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `logout_url` | string | URL de logout do Conecta com `post_logout_redirect_uri` configurada |

**Observação:** após redirecionar o usuário para `logout_url`, o frontend deve limpar o JWT armazenado localmente. O Conecta Recife redirecionará de volta ao SAÍRA para a `post_logout_redirect_uri` cadastrada após o logout bem-sucedido.

---

### 4.5 POST /integrations/conecta/revoke-consent

Revoga o consentimento de um usuário federado, atendendo à exigência da Carta de Serviços do Conecta Labs. Após a revogação, o usuário não poderá mais autenticar via Conecta Recife no SAÍRA.

**Autenticação:** requerida (Bearer JWT SAÍRA do usuário solicitante).

**Corpo da requisição (JSON):**

| Campo | Tipo | Obrigatório | Descrição |
|-------|------|-------------|-----------|
| `conecta_token` | string | sim | Token de acesso Conecta do usuário, para introspecção junto ao provedor |

**Comportamento:**

O backend realiza a introspecção do `conecta_token` junto ao endpoint de introspecção do Conecta Recife, validando que o token pertence ao usuário autenticado e está ativo. Em seguida, atualiza o campo `auth_provider` do usuário para `"conecta_revoked"`, impedindo futuras autenticações federadas. O usuário só poderá ter acesso restaurado manualmente por um administrador do SAÍRA.

**Resposta (200 OK):**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `message` | string | Confirmação da revogação bem-sucedida |

**Erros possíveis:**

| Código | Descrição |
|--------|-----------|
| 401 | Token Conecta inválido ou expirado na introspecção |
| 403 | Token Conecta não pertence ao usuário autenticado |
| 404 | Usuário não encontrado |

---

## 5. Modelo de Dados do Usuário Federado

A integração com o Conecta Recife introduz dois campos adicionais na tabela `users` do banco de dados do SAÍRA:

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `auth_provider` | string(50) | Origem da autenticação. Valores possíveis: `"local"` (padrão), `"conecta"` (autenticado via Conecta Recife), `"conecta_revoked"` (consentimento revogado) |
| `external_subject` | string(255) | Identificador único do usuário no Conecta Recife (campo `sub` do ID Token OIDC). Único e indexado no banco. |

Usuários locais possuem `auth_provider = "local"` e `external_subject = null`. Usuários federados possuem `auth_provider = "conecta"` e têm `external_subject` preenchido com o `sub` emitido pelo Conecta.

A criação de conta ocorre automaticamente no primeiro login via Conecta: se nenhum registro com aquele `external_subject` for encontrado, um novo usuário é criado com os dados extraídos do `id_token`. Logins subsequentes do mesmo usuário atualizam nome e e-mail caso tenham sido alterados no diretório do Conecta. O campo `password_hash` de usuários federados é preenchido com um hash inválido não utilizável, garantindo que não seja possível autenticá-los via login local acidentalmente.

---

## 6. Configuração do Ambiente

A integração é ativada e configurada exclusivamente por variáveis de ambiente no arquivo `.env` do serviço backend. Nenhuma alteração de código é necessária para habilitar ou desabilitar a integração.

| Variável | Exemplo | Descrição |
|----------|---------|-----------|
| `ENABLE_CONECTA_LOGIN` | `true` | Habilita os endpoints de integração e o botão no frontend |
| `ENABLE_LOCAL_LOGIN` | `true` | Mantém login local ativo em paralelo (recomendado durante homologação) |
| `CONECTA_CLIENT_ID` | `saira-mvp` | Client ID registrado no Conecta Recife |
| `CONECTA_CLIENT_SECRET` | `<segredo>` | Client Secret registrado no Conecta Recife (configurar apenas no ambiente, nunca no código) |
| `CONECTA_REALM_URL_TEST` | `https://conecta-hom.recife.pe.gov.br/auth/realms/recife` | URL base do realm de homologação do Conecta |
| `CONECTA_REALM_URL_PROD` | `https://conecta.recife.pe.gov.br/auth/realms/recife` | URL base do realm de produção do Conecta |
| `CONECTA_REDIRECT_URI` | `https://saira.recife.pe.gov.br/auth/callback` | URI de retorno após autenticação; deve estar registrada no cadastro do Conecta |
| `CONECTA_POST_LOGOUT_REDIRECT_URI` | `https://saira.recife.pe.gov.br/login` | URI de retorno após logout federado; deve estar registrada no cadastro do Conecta |
| `WEB_APP_URL` | `http://localhost:3000` | URL base da aplicação web (usada na construção de redirect URIs no ambiente de desenvolvimento) |

---

## 7. Segurança

### Proteção CSRF com State

O parâmetro `state` gerado em `/login-url` é um token criptograficamente seguro emitido pelo backend. Ele é validado no endpoint `/callback` para garantir que o fluxo de autorização foi iniciado legitimamente pela aplicação SAÍRA. Qualquer callback recebido com um `state` ausente, incorreto ou já utilizado é rejeitado com erro 400, bloqueando tentativas de Cross-Site Request Forgery.

### Troca de Código no Backend

O Authorization Code Flow garante que o `code` de autorização seja trocado por tokens OIDC exclusivamente no servidor. Em nenhum momento tokens de acesso do Conecta trafegam pelo navegador do usuário, ficam expostos em logs de frontend ou são armazenados no cliente.

### Ticket de Uso Único

O ticket interno emitido pelo `/callback` tem validade curta e é destruído após o primeiro uso em `/exchange-ticket`. Isso previne ataques de replay caso o ticket seja interceptado durante o redirecionamento entre as etapas do fluxo.

### Introspecção de Token na Revogação

O endpoint `/revoke-consent` não aceita simplesmente a identidade do usuário autenticado como suficiente para revogar acesso. Ele exige a apresentação do token Conecta ativo e realiza introspecção junto ao provedor, garantindo que apenas o titular legítimo da identidade federada — ou alguém com acesso ao token ativo — pode solicitar a revogação de seus dados.

### Senhas de Usuários Federados

Usuários criados via Conecta Recife não possuem senha local válida no SAÍRA. O campo `password_hash` é preenchido com um valor de hash intencionalmente inválido e não verificável, tornando impossível a autenticação do usuário federado por email e senha local, mesmo em caso de acesso indevido ao banco de dados.

---

## 8. Checklist de Homologação

### O que a Prefeitura precisa fornecer

| Item | Descrição |
|------|-----------|
| `client_id` | Identificador da aplicação SAÍRA registrada no ambiente de homologação do Conecta |
| `client_secret` | Segredo da aplicação no realm de homologação (quando aplicável) |
| URL do realm de homologação | Endpoint base do servidor de identidade do Conecta (Keycloak) no ambiente de teste |
| Confirmação da `redirect_uri` | URI de callback que deve estar cadastrada: `https://<domínio-saira>/auth/callback` |
| Confirmação da `post_logout_redirect_uri` | URI de pós-logout: `https://<domínio-saira>/login` |
| Escopos liberados | Mínimo necessário: `openid profile email` |

### O que o SAÍRA já tem pronto

| Entregável | Status |
|------------|--------|
| Endpoint `GET /login-url` | ✅ Implementado |
| Endpoint `GET /callback` com troca de código OIDC | ✅ Implementado |
| Endpoint `POST /exchange-ticket` | ✅ Implementado |
| Endpoint `GET /logout-url` | ✅ Implementado |
| Endpoint `POST /revoke-consent` com introspecção | ✅ Implementado |
| Sincronização automática de usuário federado no primeiro login | ✅ Implementado |
| Modo híbrido (login local e Conecta simultâneos) | ✅ Implementado |
| Ativação controlada por variável de ambiente | ✅ Implementado |
| Frontend com botão "Entrar com Conecta Recife" | ✅ Implementado |
| Tela de callback dedicada no frontend | ✅ Implementado |

### Procedimento Recomendado para Homologação

**Fase 1 — Configuração do ambiente de teste:** Preencher as variáveis `CONECTA_CLIENT_ID`, `CONECTA_CLIENT_SECRET` e `CONECTA_REALM_URL_TEST` com as credenciais fornecidas pela Prefeitura. Definir `ENABLE_CONECTA_LOGIN=true` e `ENABLE_LOCAL_LOGIN=true`. Garantir que as URIs de redirect estejam cadastradas no portal do Conecta.

**Fase 2 — Execução dos testes end-to-end:** Validar o fluxo completo com usuários reais do diretório de homologação do Conecta Recife. Testar login, logout federado e revogação de consentimento. Verificar sincronização de dados de perfil (nome, e-mail) entre o Conecta e o SAÍRA.

**Fase 3 — Decisão de política para produção:** Após homologação bem-sucedida, decidir entre manter o modo híbrido permanentemente ou evoluir para autenticação federada obrigatória, desabilitando o login local.
