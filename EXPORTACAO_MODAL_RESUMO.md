# Resumo: Exportação PNG/PDF do OccurrenceModal

## O que foi implementado
- Exportação via `html2canvas` (PNG) e `jspdf` (PDF) com dropdown de opções.
- Captura do card do modal (conteúdo visível) com `scale: 2` e `useCORS: true`.

## Problemas observados
- Erro recorrente: **"Attempting to parse an unsupported color function \"oklch\""**.
- Em alguns testes, o arquivo gerado ficou **em branco** ou com **glitches visuais**.

## Tentativas que não funcionaram bem
- **`foreignObjectRendering: true`**: evitou alguns erros, mas deixou a captura visualmente ruim (glitchy/feia).
- **Inlining de estilos no clone (`onclone`)**: cores e sombras foram aplicadas manualmente, mas o erro de `oklch` persistiu em builds.
- **Remoção de `<style>`/`<link>` no clone**: não eliminou o erro de forma consistente.
- **Normalização de cores para RGB** (incluindo `box-shadow`, `text-shadow`, `text-decoration`, `accent`, `caret`): ainda assim o parse de `oklch` continuou acontecendo em alguns cenários.
- **Substituição temporária de stylesheets** (convertendo `oklch/oklab/color()` para RGB durante a captura): mitigou parcialmente, mas não resolveu 100%.

## Diagnóstico provável
- O `html2canvas` **não suporta `oklch/oklab`** (cores do Tailwind v4), o que causa falha no parse de CSS e quebra a captura.
- Workarounds foram instáveis: ou o erro persiste, ou a qualidade visual fica ruim.

## Estado atual
- A exportação foi **postergada** e os botões foram deixados **desabilitados** como placeholder.
