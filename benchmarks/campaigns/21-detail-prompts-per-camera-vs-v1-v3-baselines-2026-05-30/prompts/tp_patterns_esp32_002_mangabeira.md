# TP-padrões (Descarte Real) — cam_11 / esp32_002 / Mangabeira

Extraídos do spreadsheet `Ocorrências Capturadas` em 2026-05-30.
**17 CONFIRMADOs** dos 81 eventos. Volumes 0,01–0,75 m³, mediana ~0,05 m³.

## Distribuição (vocabulário literal do operador)

| n | Padrão | Justificativa literal | Volume típico |
|---|---|---|---|
| 6 | **Pedestre com saco** | "Um homem realizando o descarte de um saco de lixo / múltiplas coisas" | 0,01–0,05 m³ |
| 3 | **Pedestre com carrinho de mão** | "homem realizando o descarte utilizando um carrinho de mão" | 0,01–0,1 m³ |
| 3 | **Poda pedestre** | "Homem descartando restos de poda" / "homem descartando restos de poda com um carrinho de mão" | 0,1–0,75 m³ |
| 1 | **Pedestre uniforme** | "Grande quantidade de lixo descartada por um homem utilizando uniforme laranja" | 0,1 m³ |
| 1 | **Pedestre objetos grandes** | "Homem descartando tábuas de madeira" | 0,05 m³ |
| 1 | **Pedestre construção** | "Homem realizando o descarte de materiais de construção" | 0,01 m³ |
| 1 | **Ciclista descartando** | "Homem de bicicleta realizando descarte de lixo" | 0,08 m³ |
| 1 | **Múltiplos descartes seguidos** | "Pessoas descartando lixo. Primeiramente um descarte feito com um carrinho de mão e posteriormente um [outro]" | 0,25 m³ |
| 1 | **Sacola conteúdo** | "Um homem realizando o descarte do conteúdo de uma sacola branca. Retirando conteúdo dela e colocando" | 0,05 m³ |
| 1 | **Descarte DURANTE limpeza** | "Literalmente enquanto o pessoal da prefeitura está limpando o local passa um homem e realiza o desca[rte]" | 0,01 m³ |
| 1 | **Múltiplos itens** | "Homem realizando o descarte do conteúdo de um carrinho de mão" | 0,1 m³ |

## Síntese para o prompt

**Bloco "PADROES DE DESCARTE REAL NESTA CAMERA":**

- **97% dos descartes são PEDESTRES** (16/17). Apenas 1 cita "uniforme laranja" e mesmo assim é pedestre,
  não caminhão. **Veículo NÃO é requisito** nesta câmera.
- **Volumes minúsculos**: mediana ~0,05 m³ (1 sacola pequena). **PILHA PODE NÃO MUDAR VISUALMENTE**
  entre primeiro e último frame. NÃO usar ausência de crescimento como contraevidência.
- **Veículos auxiliares pedestres**: carrinho de mão, bicicleta carregada, sacola — todos sinais positivos
  quando combinados com postura de depósito.
- **Modalidades de descarte observadas**:
  1. Pessoa AGACHADA/INCLINADA na pilha colocando saco/objeto
  2. Pessoa em pé largando saco e seguindo (mãos antes cheias, depois vazias)
  3. Pessoa "retirando conteúdo da sacola" — esvaziando recipiente na pilha
  4. Carrinho/bicicleta posicionado AO LADO da pilha, fluxo de carga indo PARA o chão
- **Uniforme NÃO isenta**: existe pelo menos 1 confirmação com "uniforme laranja" depositando.
  E há caso de "descarte DURANTE limpeza" — depositor real entra DURANTE atividade de EMLURB.
- **Tipos de material**: predominantemente Lixo Domiciliar (n=12), Poda (n=3), Entulho (n=0 nesta
  cam — entulho costuma ser veículo, ausente aqui).
