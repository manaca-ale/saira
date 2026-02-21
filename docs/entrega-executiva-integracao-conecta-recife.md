# Entrega Executiva: Integracao SAIRA x Conecta Recife

## 1. Resumo Executivo

Data de referencia: 18 de fevereiro de 2026.

O sistema SAIRA esta pronto para iniciar a homologacao oficial com o Conecta Recife Login, em conformidade com o roteiro tecnico recebido da Prefeitura do Recife.

O projeto foi implementado em modo hibrido, preservando o login local atual e adicionando login federado via Conecta Recife. Isso reduz risco de transicao, evita indisponibilidade para usuarios internos e permite homologacao controlada por ambiente.

## 2. Status Atual da Integracao

Status: pronto para homologacao com a Prefeitura.

Ja implementado:

- fluxo OIDC no backend (authorization code);
- callback e troca de credenciais no backend (sem troca de token no frontend);
- sincronizacao de usuario federado no SAIRA;
- emissao de sessao/token interno SAIRA apos autenticacao Conecta;
- logout SSO com geracao de URL de saida do Conecta;
- endpoint de revogacao de dados pessoais com introspeccao de token;
- habilitacao por flags de ambiente para rollout seguro.

## 3. Principais Entregas Tecnicas

Endpoints implementados em `/api/v1/integrations/conecta`:

- `GET /login-url`
- `GET /callback`
- `POST /exchange-ticket`
- `GET /logout-url`
- `POST /revoke-consent`

Adequacoes de identidade local:

- suporte a `auth_provider` (`local`, `conecta`, `conecta_revoked`);
- suporte a `external_subject` para vinculacao de identidade federada;
- manutencao do login local em paralelo.

Experiencia do usuario:

- tela de login com opcao `Entrar com Conecta Recife`;
- fluxo de callback dedicado no frontend;
- botao com identidade visual do Conecta Recife.

## 4. Evidencia de Operacao

Stack validada em Docker:

- frontend: `http://localhost:3000`
- backend: `http://localhost:8001`
- banco: `localhost:5432`
- redis: `localhost:6379`

Health check:

- `GET /health` no backend retornando `200`.

Base de homologacao populada:

- users: 2
- cameras: 9
- detections: 1170
- offenders: 5
- detection_offenders: 681

## 5. O que a Prefeitura Precisa Fornecer para Teste Oficial

Para homologacao com o Conecta Recife (ambiente de teste):

- `client_id`;
- `client_secret` (quando aplicavel);
- confirmacao das URIs cadastradas:
- redirect URI da aplicacao;
- post logout redirect URI;
- confirmacao dos escopos liberados (minimo: `openid profile email`).

## 6. Modelo de Implantacao Recomendado

Fase 1: homologacao controlada

- manter `ENABLE_LOCAL_LOGIN=true`;
- ativar `ENABLE_CONECTA_LOGIN=true`;
- executar testes end-to-end com usuarios da Prefeitura.

Fase 2: decisao de producao

- apos homologacao, decidir politica final:
- manter modo hibrido;
- ou evoluir para federacao obrigatoria.

## 7. Riscos e Mitigacoes

Riscos principais:

- divergencia de `redirect_uri` entre cadastro e aplicacao;
- indisponibilidade de credenciais oficiais durante janela de teste;
- erro de configuracao de ambiente (client id/secret).

Mitigacoes implementadas:

- modo hibrido com fallback local;
- configuracao por variaveis de ambiente;
- endpoint de revogacao com validacao de token por introspeccao.

## 8. Conclusao

O SAIRA encontra-se tecnicamente apto para integrar com o Conecta Recife Login e iniciar homologacao imediata com a Prefeitura do Recife.

A principal dependencia externa para fechamento da integracao e a disponibilizacao/validacao das credenciais e URIs oficiais no ambiente de teste da Prefeitura.
