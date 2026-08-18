# Anti-padrões (Falso Positivo) — cam_11 / esp32_002 / Mangabeira

Extraídos do spreadsheet `Ocorrências Capturadas` (1wABg4qMYFR5IHG0lWlj0CBhL2jm5c_ARJQjdDXpvqko)
em 2026-05-30. Total: **64 FPs** dos 81 eventos confirmados de Mangabeira.

## Distribuição por padrão (com vocabulário literal do operador)

| Frequência | Padrão | Justificativa literal do operador |
|---|---|---|
| 13 | **Coleta informal de catador** | "Estavam retirando o Lixo" |
| 13 | **Limpeza/poda EMLURB** | "Estavam limpando os restos de poda" |
| 11 | **Passantes na calçada** | "Pessoas passando" / "Apenas pessoas passando" |
| 2 | **Poda em execução** | "Estavam realizando a poda" |
| 2 | **Catador sorteando** | "Apenas um homem vasculhando o lixo" |
| 2 | **Vento movendo papel/saco** | "pessoas passando e o vento movimentando o lixo" |
| 2 | **Carros estacionando** | "Carro apenas estacionou" / "Caminhão estacionado" |
| 1 | **Pessoa com carrinho passando** | "Pessoa passando com um carrinho" |
| 1 | **Pessoa entrando carro** | "Pessoa apenas estacionou e desceu com uma criança" |
| 1 | **Bicicleta passando** | "Apenas um homem passando de bicicleta" |
| 1 | **Bicicleta carregando sacos** | "homem passando com uma bicicleta carregada de sacos (ele não realiza)" |
| 1 | **Pombos+passantes** | "Pessoas passando e pombos andando sobre o lixo" |
| 1 | **Sacos atravessando** | "Homem passa com sacos de lixo na mão mas não realiza o descarte na área" |
| 1 | **Sorting entre 2 pessoas** | "Dois homens trocando objetos, parece um descarte mas eles apenas usam o local pa[ra trocar]" |
| 1 | **Limpeza prefeitura** | "Pessoal da prefeitura realizando a limpeza" |
| 1 | **Várias pessoas com sacos não depositando** | "Várias pessoas passam com sacos que parecem de lixo, contudo nenhuma aparenta te[r descartado]" |
| 1 | **Pega-larga-pega** | "Homem joga algo no local e parece passar algo nesse objeto, depois o pega e vai" |
| 1 | **Catador genérico** | "Homem vasculhando o lixo" |
| 1 | **Pombos isolados** | "pombos andando perto do lixo" |
| outros | passantes c/ veículos parados, motos | n=2 |

## Síntese para o prompt

**Bloco "PADROES DE FALSO POSITIVO COMUNS NESTA CAMERA":**

1. **Coleta/limpeza/poda EMLURB** (28/64 = 44%): caminhão compactador parado + pessoas com sacos/vassouras/ancinhos
   levando material do chão para o caminhão; pilha DIMINUI ou some. Uniforme laranja típico.
   - Inclui: "limpando restos de poda", "realizando a poda", "pessoal da prefeitura limpando"
2. **Passantes** (16/64 = 25%): pessoas/bicicletas/motos/carros atravessando o quadro em LINHA RETA
   sem parar na pilha. Posições MUITO diferentes entre frames.
3. **Catador vasculhando** (4/64): pessoa AGACHADA na pilha mas levando material DO CHÃO PARA carroça/sacola
   pessoal — direção oposta a descarte.
4. **Pessoas COM saco que apenas atravessam** (3/64): "carregando sacos" não basta — exige PARADA
   COM DEPOSITO. Pessoa que cruza o quadro com saco e segue NÃO é descarte.
5. **Sorting entre 2 pessoas** (1/64): duas pessoas trocando objetos no local sem descartar — usam
   o ponto como referência.
6. **Pombos / vento / sombras** (3/64): movimento na pilha que não é humano.
7. **Carros estacionando** (2/64): só estacionar, sem descarregar nada do veículo.
