# Entrega: Integracao SAIRA com Conecta Recife Login

## Status da Entrega

Data de referencia: 18 de fevereiro de 2026.

O SAIRA esta tecnicamente pronto para a integracao com o Conecta Recife Login, em modo hibrido:

- login local (email/senha) continua ativo;
- login via Conecta Recife ja implementado;
- callback OIDC, troca de ticket, logout SSO e endpoint de revogacao LGPD implementados;
- stack validada em Docker com frontend, backend, banco e redis ativos.

## Objetivo

Atender ao roteiro da Prefeitura do Recife para autenticacao via OpenID Connect (OIDC) e habilitar o uso do SAIRA no ecossistema Conecta, com seguranca, rastreabilidade e baixo impacto no sistema existente.

## Escopo Implementado

### 1. Login Hibrido

- Fluxo local mantido em `POST /api/v1/auth/login`.
- Fluxo Conecta Recife habilitado em paralelo.
- Frontend com duas opcoes na tela de login:
- Entrar (local)
- Entrar com Conecta Recife

### 2. Endpoints de Integracao Conecta

Base: `/api/v1/integrations/conecta`

- `GET /login-url`
- gera `state` e URL de autorizacao no Conecta Recife
- `GET /callback`
- recebe `code + state`, troca token no Conecta, consulta userinfo, sincroniza usuario local e gera ticket temporario
- `POST /exchange-ticket`
- troca ticket temporario por JWT interno do SAIRA
- `GET /logout-url`
- gera URL de Single Sign-Out no Conecta
- `POST /revoke-consent`
- valida Bearer token via `/token/introspect` e executa revogacao de dados locais

### 3. Persistencia de Identidade Externa

Tabela `users` atualizada com:

- `auth_provider` (`local`, `conecta`, `conecta_revoked`)
- `external_subject` (identificador externo do provedor)

Migracao aplicada: `e6f7a8b9c0d1_add_conecta_identity_fields.py`.

### 4. Configuracao em Docker

Variaveis de ambiente adicionadas para todos os compose files:

- `ENABLE_LOCAL_LOGIN`
- `ENABLE_CONECTA_LOGIN`
- `CONECTA_ENV`
- `CONECTA_CLIENT_ID`
- `CONECTA_CLIENT_SECRET`
- `CONECTA_REDIRECT_URI`
- `CONECTA_POST_LOGOUT_REDIRECT_URI`
- demais parametros OIDC de timeout/scope/base URL

## Aderencia ao Roteiro da Prefeitura

Itens da cartilha atendidos:

- uso de Authorization Code Flow (OIDC)
- troca de `code` no backend (nao no frontend)
- suporte a logout no provedor
- endpoint para revogacao com introspeccao de token
- possibilidade de operacao em ambiente de teste e producao

## O que a Prefeitura precisa fornecer para homologacao

Para iniciar testes com credencial oficial do Conecta Recife (ambiente de teste), sao necessarios:

- `client_id`
- `client_secret` (quando client confidential)
- confirmacao de `redirect_uri` cadastrada
- confirmacao de `logout redirect_uri` cadastrada
- validacao dos escopos autorizados (minimo `openid profile email`)

## URLs que devem ser cadastradas no Conecta

Exemplo de homologacao:

- Redirect URI do SAIRA:
- `https://<dominio-saira>/api/v1/integrations/conecta/callback`
- Post-logout redirect:
- `https://<dominio-saira>/`

## Evidencia tecnica do ambiente

Stack validada em Docker:

- frontend: `http://localhost:3000`
- backend: `http://localhost:8001`
- health backend: `GET /health` retornando `200`
- banco e redis ativos

Base populada para testes funcionais:

- users: 2
- cameras: 9
- detections: 1170
- offenders: 5
- detection_offenders: 681

## Fluxo de Teste Recomendado com a Prefeitura

1. Prefeitura fornece credenciais de teste e confirma URIs cadastradas.
2. Time SAIRA habilita `ENABLE_CONECTA_LOGIN=true` no ambiente de homologacao.
3. Usuario acessa login e seleciona "Entrar com Conecta Recife".
4. Conecta redireciona para callback do SAIRA.
5. SAIRA cria sessao e redireciona para dashboard.
6. Validar logout SSO.
7. Validar endpoint de revogacao com token ativo.

## Resultado

O sistema esta pronto para iniciar homologacao de integracao com a Prefeitura do Recife.
A pendencia principal para virada de teste oficial e a entrega/ativacao das credenciais do Conecta Recife e o cadastro final das URIs no provedor.
