# Plano: Documentação Técnica da API SAÍRA

Data de referência: 21 de fevereiro de 2026.

## 1. Objetivo

Produzir dois documentos técnicos em Google Docs com o estilo e formatação do documento de referência "Arquitetura de Software — Projeto SAÍRA":

| # | Documento | Escopo |
|---|-----------|--------|
| 1 | **Documentação da API — Integração Conecta Recife** | Endpoints OIDC, fluxo de autenticação federada, configuração e checklist de homologação |
| 2 | **Relatório Técnico — API CRUD de Ocorrências e Alertas** | Endpoints de detecções, câmeras, infratores, notificações em tempo real e dashboard analítico |

---

## 2. Bases de Referência

- **Estilo/formatação:** Documento "Arquitetura de software — Projeto SAÍRA" (ID: `1cO-mdNEcDrfUine3PFqQA3D36vYmWr_mHv0dGBVEB6g`)
- **Conteúdo técnico:** Código-fonte em `services/backend/app/`
- **Contexto executivo:** `docs/entrega-executiva-integracao-conecta-recife.md` e `docs/entrega-executiva-backend-saira.md`

---

## 3. Estrutura dos Documentos

### Documento 1 — Integração Conecta Recife

```
Projeto SAÍRA
Documentação da API — Integração Conecta Recife

SUMÁRIO

1. Visão Executiva
2. Contexto da Integração
   2.1 Protocolo OIDC (OpenID Connect)
   2.2 Modelo de autenticação híbrida
3. Fluxo de Autenticação Federada
   3.1 Diagrama do fluxo
   3.2 Passo a passo técnico
4. Referência de Endpoints
   4.1 GET /integrations/conecta/login-url
   4.2 GET /integrations/conecta/callback
   4.3 POST /integrations/conecta/exchange-ticket
   4.4 GET /integrations/conecta/logout-url
   4.5 POST /integrations/conecta/revoke-consent
5. Modelo de Dados do Usuário Federado
6. Configuração do Ambiente
7. Segurança
8. Checklist de Homologação
```

### Documento 2 — CRUD de Ocorrências e Alertas

```
Projeto SAÍRA
Relatório Técnico — API de Ocorrências e Alertas

SUMÁRIO

1. Visão Executiva
2. Arquitetura do Módulo
   2.1 Stack tecnológica
   2.2 Topologia de serviços
3. Modelos de Dados
   3.1 Detecção (Ocorrência)
   3.2 Câmera
   3.3 Infrator (Offender)
   3.4 Notificação
4. API de Ocorrências (Detecções)
   4.1 Listar ocorrências
   4.2 Busca avançada com filtros
   4.3 Detalhes de uma ocorrência
   4.4 Criar ocorrência
   4.5 Iniciar análise
   4.6 Resolver ocorrência
   4.7 Atualizar e excluir
5. API de Câmeras
6. API de Infratores
   6.1 Cadastro e consulta
   6.2 Vínculos com ocorrências
   6.3 Dashboard analítico de infratores
7. Sistema de Alertas em Tempo Real
   7.1 Fluxo Redis Pub/Sub + SSE
   7.2 Endpoints de notificações
8. Dashboard Analítico
9. Autenticação e Segurança
10. Códigos de Erro e Tratamento
```

---

## 4. Padrão de Formatação (baseado no doc de referência)

- **Idioma:** Português brasileiro
- **Tom:** Técnico e formal, mas acessível — conceitos explicados inline
- **Títulos:** Hierarquia clara com numeração de seções
- **Tabelas:** Para endpoints (método, caminho, descrição) e parâmetros
- **Blocos de texto:** Parágrafos completos, sem listas excessivas — prosa profissional
- **Código:** Inline para nomes de campos/endpoints; blocos separados para exemplos JSON
- **Siglas:** Explicadas na primeira ocorrência (ex: OIDC — OpenID Connect)

---

## 5. Plano de Execução

### Etapa 1 — Preparação (automático)
- [x] Ler código-fonte dos endpoints e modelos
- [x] Ler docs executivos de referência
- [x] Ler documento de estilo de referência
- [x] Rascunhar conteúdo completo dos dois documentos em Markdown

### Etapa 2 — Criação no Google Drive (automático)
- [x] Criar documentos na pasta https://drive.google.com/drive/folders/1S-me2c8NZwkpDjMDDBjJbQU9M5NYH77N?usp=drive_link
- [x] Importar Documento 1 via `import_to_google_doc`
- [x] Importar Documento 2 via `import_to_google_doc`

Documentos criados (21/02/2026):
- Documento 1 — Documentação da API - Integração Conecta Recife  
  ID: `1AL_pks03gfxc_HZNn6srnhOwQkSuCz6gaZs1eOS_zvw`  
  Link: https://docs.google.com/document/d/1AL_pks03gfxc_HZNn6srnhOwQkSuCz6gaZs1eOS_zvw/edit?usp=drivesdk
- Documento 2 — Relatório Técnico - API CRUD de Ocorrências e Alertas  
  ID: `1mBcBg8PDk8X9CN7Tiir9C2tbYPSGvNO8UyxgNKWoa-Q`  
  Link: https://docs.google.com/document/d/1mBcBg8PDk8X9CN7Tiir9C2tbYPSGvNO8UyxgNKWoa-Q/edit?usp=drivesdk

### Etapa 3 — Ajustes finais (manual pelo usuário)
- [ ] Adicionar imagens/diagramas se necessário
- [ ] Mover para pasta definitiva se precisar de outro local
- [ ] Revisar links de endpoints conforme ambiente de produção

---

## 6. Observações Técnicas

- Os documentos serão criados via `import_to_google_doc` com conteúdo Markdown — o Google Drive converte automaticamente headings, tabelas e negrito.
- Cada seção de endpoint seguirá o padrão: método HTTP + caminho + descrição + parâmetros em tabela + exemplo de resposta.
- Campos sensíveis (client_secret, JWT) serão indicados como `<CONFIGURAR_NO_ENV>` nos exemplos.
- O fluxo de tratamento de ocorrências (Pendente → Em Análise → Resolvido) será documentado com diagrama textual (ASCII).
