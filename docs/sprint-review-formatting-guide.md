# Guia de Formatação — Relatório Sprint Review SAÍRA

> Mapeamento completo do padrão visual do Google Doc
> **Documento de referência:** [Relatório Sprint Review 3 - Projeto SAÍRA](https://docs.google.com/document/d/1DrirT1KAZhgdutUUg205DxB3FC_GZltXqeEM2STzlEo/edit)

---

## 1. Layout de Página

| Propriedade         | Valor                              |
|---------------------|------------------------------------|
| Formato             | A4 — 595 × 842 pt (210 × 297 mm)  |
| Orientação          | Retrato (Portrait)                 |
| Margem superior     | 72 pt (2,54 cm / 1 in)            |
| Margem inferior     | 72 pt                              |
| Margem esquerda     | 72 pt                              |
| Margem direita      | 72 pt                              |
| Margem de cabeçalho | 14 pt (≈ 0,5 cm)                  |
| Margem de rodapé    | 71 pt (≈ 2,5 cm)                  |
| Fundo de página     | Branco (sem cor de fundo)          |
| Modo de documento   | Paginado (PAGES)                   |
| Numeração de página | Começa em 1                        |

---

## 2. Paleta de Cores

| Nome                  | RGB decimal                              | HEX       | Uso                                      |
|-----------------------|------------------------------------------|-----------|------------------------------------------|
| **Azul Marinho SAÍRA**| R 26 · G 23 · B 75                       | `#1A174B` | Texto normal, Heading 3, cor principal   |
| **Branco**            | R 255 · G 255 · B 255                    | `#FFFFFF` | Texto da capa (sobre fundo escuro)       |
| **Cinza Cabeçalho**   | R 239 · G 239 · B 239                    | `#EFEFEF` | Fundo da linha de cabeçalho das tabelas  |
| **Quase-preto**       | R 31 · G 31 · B 31                       | `#1F1F1F` | Bordas de células das tabelas            |
| **Cinza médio**       | R 102 · G 102 · B 102                    | `#666666` | Heading 4 e Heading 5                    |

---

## 3. Tipografia

### Família tipográfica

- **Fonte principal:** `Sora` (weight 400 — Regular)
- Aplicada a todos os estilos: texto normal, headings, tabelas

### Estilos de texto por nível

| Estilo Google Doc | Tamanho | Peso    | Cor         | Observações                              |
|-------------------|---------|---------|-------------|------------------------------------------|
| `SUBTITLE`        | 19 pt   | Regular | `#FFFFFF`   | Usado na capa; alinhamento centralizado  |
| `HEADING_2`       | 17 pt   | **Bold**| herda texto | Seções principais; justificado           |
| `HEADING_3`       | 13 pt   | **Bold**| `#1A174B`   | Sub-seções de entrega; recuo 72 pt       |
| `HEADING_4`       | 12 pt   | Regular | `#666666`   | Sem uso visível no doc de referência     |
| `HEADING_5`       | herda   | Regular | `#666666`   | Sem uso visível no doc de referência     |
| `NORMAL_TEXT`     | 11 pt   | Regular | `#1A174B`   | Corpo de texto padrão                    |

### Estilo de parágrafo — NORMAL_TEXT

| Propriedade         | Valor                        |
|---------------------|------------------------------|
| Alinhamento         | Justificado                  |
| Espaçamento de linha| 115%                         |
| Recuo da 1ª linha   | 36 pt                        |
| Espaço acima        | 0 pt                         |
| Espaço abaixo       | 0 pt                         |
| Modo de espaçamento | NEVER_COLLAPSE               |

### Espaçamento dos Headings

| Estilo      | Espaço acima | Espaço abaixo | Recuo início | Recuo 1ª linha |
|-------------|-------------|--------------|--------------|----------------|
| HEADING_1   | herda        | herda        | 36 pt        | 18 pt          |
| HEADING_2   | herda        | herda        | —            | —              |
| HEADING_3   | 16 pt        | 4 pt         | 72 pt        | —              |
| HEADING_4   | 14 pt        | 4 pt         | —            | —              |

---

## 4. Estrutura do Documento

### Capa

```
[8 linhas em branco — espaçamento vertical visual]
[Imagem do logo SAÍRA — 341 × 90 pt, centralizada, estilo SUBTITLE]
[Texto: "Projeto SAIRA | Sprint review - 3"]  ← SUBTITLE, centralizado, branco
[Texto: "02/02/26 - 23/02/26"]               ← SUBTITLE, 19pt, centralizado, branco
```

- A capa usa estilo `SUBTITLE` com **texto branco**, sugerindo fundo escuro
- O fundo escuro da capa é provido por um **elemento visual** (imagem de cobertura / box colorido)
- Cabeçalho da primeira página (`firstPageHeader`) está vazio — comportamento distinto do header padrão

### Sumário

- Bloco do tipo `table_of_contents` (automático do Google Docs)
- Posicionado logo após o título "SUMÁRIO" em `HEADING_2`
- Recuo de entrada: —

### Corpo do documento

```
HEADING_2   → 1. Visão Geral
NORMAL_TEXT → corpo do parágrafo
HEADING_2   → 2. Status dos Itens Programados
              [TABELA 1]
HEADING_2   → 3. Detalhamento das Entregas
  HEADING_3   → 3.1. Nome da entrega
  NORMAL_TEXT → Descrição introdutória
  NORMAL_TEXT → **Ação:** texto (bold + regular inline)
  NORMAL_TEXT → **Resultado:** texto (bold + regular inline)
HEADING_2   → 4. Artefatos Desenvolvidos
NORMAL_TEXT → parágrafo introdutório
              [TABELA 2]
```

---

## 5. Padrão de Labels em Negrito (Inline Bold)

Dentro de parágrafos `NORMAL_TEXT`, labels específicos são formatados em bold inline:

| Label            | Uso                                     |
|------------------|-----------------------------------------|
| **Ação:**        | Descreve a ação executada               |
| **Resultado:**   | Descreve o resultado alcançado          |
| **Telas Entregues:** | Lista de telas do protótipo        |
| **ID** (tabela)  | Cabeçalho de coluna em tabelas          |

Recuo do parágrafo onde esses labels aparecem: **36 pt** a partir da margem esquerda.

---

## 6. Tabelas

### Estilo comum a ambas as tabelas

| Propriedade          | Valor                         |
|----------------------|-------------------------------|
| Borda (todos os lados)| 0,68 pt, sólido, `#1F1F1F`  |
| Padding superior     | 6 pt                          |
| Padding inferior     | 6 pt                          |
| Padding esquerdo     | 9 pt                          |
| Padding direito      | 9 pt                          |
| Alinhamento vertical | TOP                           |
| Fundo cabeçalho      | `#EFEFEF` (cinza claro)       |
| Fundo dados          | branco (sem cor)              |
| Texto cabeçalho      | Bold                          |

### Tabela 1 — Status dos Itens Programados (7 linhas × 3 colunas)

| Coluna          | Largura    | Conteúdo         |
|-----------------|------------|------------------|
| ID              | 31,5 pt    | Número do item   |
| Item Programado | 354 pt     | Descrição        |
| Status          | 56,25 pt   | [✅] ou similar  |

### Tabela 2 — Artefatos Desenvolvidos (8 linhas × 4 colunas)

| Coluna      | Largura    | Conteúdo                    |
|-------------|------------|-----------------------------|
| ID          | 73,5 pt    | Código ART-xx               |
| Artefato    | 133,5 pt   | Nome do entregável          |
| Tipo        | 90 pt      | PDF Técnico / Site / etc.   |
| Localização | 143,25 pt  | Link ou caminho             |

---

## 7. Imagens e Elementos Visuais

| ID Objeto | Dimensões (pt)       | Posição / Estilo     | Uso provável       |
|-----------|---------------------|----------------------|--------------------|
| `i.0`     | 341 × 90 pt         | SUBTITLE, centralizado | Logo SAÍRA na capa |
| `i.1`     | 322 × 16 pt         | —                    | Linha decorativa / barra |
| `i.2`     | 36 × 38 pt          | —                    | Ícone / logo pequeno |

---

## 8. Cabeçalho e Rodapé

- **Cabeçalho da 1ª página:** vazio (campo separado — `firstPageHeader`)
- **Cabeçalho padrão:** vazio (sem texto visível)
- **Rodapé padrão:** vazio (sem texto visível detectado via API)
- `useFirstPageHeaderFooter: true` — a primeira página tem cabeçalho/rodapé próprio

---

## 9. Checklist para Novos Documentos no Mesmo Padrão

- [ ] Página A4, margem 72 pt (1 in) em todos os lados
- [ ] Fonte **Sora Regular 400** em todo o documento
- [ ] Cor primária de texto: `#1A174B`
- [ ] Capa: texto branco centralizado (SUBTITLE), logo centralizado
- [ ] Sumário automático após a capa
- [ ] Seções com HEADING_2 bold 17pt
- [ ] Sub-seções com HEADING_3 bold 13pt cor `#1A174B`, recuo 72pt
- [ ] Labels **Ação:** e **Resultado:** em bold inline, parágrafo com recuo 36pt
- [ ] Tabelas com header `#EFEFEF`, borda `#1F1F1F` 0,68pt, padding 6/9pt
- [ ] Texto das tabelas em Sora, cabeçalho em bold
