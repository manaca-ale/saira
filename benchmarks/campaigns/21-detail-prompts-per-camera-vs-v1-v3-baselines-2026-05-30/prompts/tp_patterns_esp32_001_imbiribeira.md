# TP-padrões (Descarte Real) — cam_10 / esp32_001 / Imbiribeira

Extraídos do spreadsheet `Ocorrências Capturadas` em 2026-05-30.
**10 CONFIRMADOs** dos 84 eventos. Volumes 0–1,5 m³ (mais variados que Mangabeira).

## Distribuição (vocabulário literal do operador)

| n | Modalidade | Justificativa literal | Volume |
|---|---|---|---|
| 2 | **Pedestres com objeto grande** | "Dois homens descartando o conteúdo dentro de um grande saco/pano branco" / "Dois homens realizando o descarte de objetos grandes" | 0,1–0,15 m³ |
| 1 | **Pedestre com carrinho** | "Um homem realizando o descarte de lixo com um carrinho de mão" | 0,05 m³ |
| 1 | **Caminhonete grande volume** | "Caminhonete azul escura realiza o descarte de um grande volume de lixo" | 0,5 m³ |
| 1 | **Carro escuro** | "Carro escuro (preto) realizando descarte de lixo" | 0 m³ (não medido) |
| 1 | **Pessoas com sacola marrom** | "Pessoas realizando o descarte do conteúdo de um saco marrom aparentemente" | 1,5 m³ |
| 1 | **Mexendo+descarte** | "Os dois homens ainda estavam mexendo no lixo, mas no final aparece um outro homem que realiza um des[carte]" | 0,1 m³ |
| 1 | **Mini caminhão** | "Pessoas descarregando lixo de um mini caminhão" | 0,8 m³ |

## Síntese para o prompt

**Bloco "PADROES DE DESCARTE REAL NESTA CAMERA":**

- **50% veículos + 50% pedestres** — cenário HÍBRIDO. Não privilegiar uma modalidade sobre outra.
- **Modalidades observadas**:
  1. **Pedestres com objeto/saco/carrinho** (n=5): equivalente a Mangabeira mas volumes maiores
     (0,05–1,5 m³, mais visível na pilha)
  2. **Veículo (caminhonete/carro/mini caminhão) descarregando** (n=5):
     - Veículo PARADO (mesma posição em 2+ frames)
     - Pessoa ESTACIONÁRIA entre veículo e chão, manuseando material
     - Material visivelmente indo DE dentro do veículo PARA o chão/pilha
- **Discriminador chave caminhão coleta EMLURB vs caminhão descarregando**:
  - COLETA: caminhão COMPACTADOR (carroceria fechada com hopper traseiro), pessoas levando DO CHÃO PARA o caminhão, pilha DIMINUI
  - DESCARGA: caminhonete / mini caminhão / pickup / baú com carroceria aberta, pessoas levando DO VEÍCULO PARA o chão, pilha CRESCE
- **Volumes maiores que cam_11**: 0,05–1,5 m³ → pilha geralmente CRESCE visualmente entre frames.
  Pile-volume-delta É um sinal útil aqui (diferente de Mangabeira).
- **Tipos de material**: Lixo Domiciliar (n=8), Entulho (n=2). Entulho aparece, então o sinal
  "caminhão de obra/caçamba com entulho" pode ser válido.

## Eventos complicados (avisar o modelo)

- "Os dois homens ainda estavam mexendo no lixo, mas no final aparece um outro homem que realiza um descarte"
  → primeiros frames podem parecer FP (sorting), mas evento real acontece em frames TARDIOS.
  Reforça importância de não decidir só pelo primeiro frame.
