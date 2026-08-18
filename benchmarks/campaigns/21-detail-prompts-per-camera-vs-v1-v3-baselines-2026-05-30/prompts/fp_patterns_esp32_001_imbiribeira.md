# Anti-padrões (Falso Positivo) — cam_10 / esp32_001 / Imbiribeira

Extraídos do spreadsheet `Ocorrências Capturadas` em 2026-05-30.
**50 FPs** dos 84 eventos confirmados de Imbiribeira (10 CON + 24 indef + 50 FP).

## Distribuição por padrão (vocabulário literal do operador)

| Frequência | Padrão | Justificativa literal |
|---|---|---|
| 14 | **Trânsito misto pessoas+veículos** | "Apenas pessoas e veículos passando" |
| 9 | **Caminhão de coleta EMLURB** | "Caminhão realizando a retirada de lixo" / "Coleta do lixo sendo realizada" / "Lixo sendo recolhido pelo caminhão de coleta" |
| 2 | **Passantes** | "Pessoas passando" |
| 2 | **Chuva** | "Apenas está chovendo" |
| 1 | **Limpeza local** | "Estavam realizando limpeza na área" / "Pessoal realizando a limpeza do local" |
| 1 | **Carro passando** | "Veículos passando" |
| 1 | **Sem evento** | "Nada ocorrendo" |
| 1 | **Pessoa carrinho passando** | "Pessoa passando com um carrinho" |
| 1 | **Cachorro** | "Apenas um cachorro andando" |
| 1 | **Carroça (sorting)** | "Apenas pessoas passando e mexendo em uma carroça" |
| 1 | **Carroça (sorting solo)** | "Apenas uma pessoa mexendo na carroça" |
| 1 | **Cães+pessoas misturado** | "Apenas pessoas, veículos e dois cachorros andando perto da região onde o descart[e ocorre]" |
| 1 | **Cão+pessoas** | "Apenas pessoas, veículos e um cachorro andando perto da região onde o descarte é [feito]" |
| 1 | **Conversa em veículo** | "Apenas um homem conversando com uma pessoa dentro de um caminhão passando" |
| 1 | **Catador (homem)** | "Homem vasculhando o lixo" (×2) |
| 1 | **Catador (pessoas)** | "Pessoas mexendo no lixo" |
| 1 | **Catador (mexer)** | "Homem mexendo no lixo" |
| 1 | **Carros estacionados** | "Apenas carros estacionados" |
| 1 | **Trânsito intenso** | "Apenas pessoas, carros e caminhões passando e/ou parados" |
| 1 | **Dois homens carregando** | "Apenas dois homens carregando um item grande (não realizam o descarte)" |
| 1 | **Caminhão estacionado** | "Apenas um caminhão estacionado" |
| 1 | **Catador pega papelão** | "Homem apenas pegou um papelão do lixo" |

## Síntese para o prompt

**Bloco "PADROES DE FALSO POSITIVO COMUNS NESTA CAMERA":**

1. **Trânsito misto** (17/50 = 34%): pessoas + carros + ônibus passando em LINHA RETA. Posições MUITO
   diferentes entre frames. NÃO há parada na pilha. Inclui cães, motos, ciclistas.
2. **Caminhão de coleta EMLURB / coleta municipal** (11/50 = 22%):
   - Caminhão COMPACTADOR de hopper traseiro PARADO
   - Pessoas com sacos/vassouras levando material DO CHÃO PARA o caminhão
   - Pilha DIMINUI
   - **CRÍTICO**: confundir com "veículo descarregando" é o erro mais comum.
     Discriminador → DIRECÇÃO DO MATERIAL: vai DO CHÃO para o caminhão = COLETA, NÃO descarte.
3. **Catador vasculhando** (5/50 = 10%): pessoa parada/agachada na pilha **levando objeto DA PILHA PARA**
   carroça ou bolsa pessoal. Direção oposta a descarte. Inclui "pegar papelão", "mexer no lixo".
4. **Carroça (sorting)** (2/50): pessoa mexendo na própria carroça parada perto da pilha — pode estar
   organizando recicláveis. Decide pela direção do fluxo de material.
5. **Veículos parados sem descarga** (2/50): caminhão/carro estacionado sem ninguém manuseando material
   entre veículo e chão.
6. **Pessoas carregando item grande sem depositar** (1/50): "dois homens carregando objeto grande
   (não realizam descarte)" — usam o local de passagem.
7. **Chuva** (2/50): blur, distorção visual. Pode ativar falsos sinais de movimento.
8. **Cão/animal** (3/50): movimento na cena sem agente humano de descarte.
9. **Conversa no veículo** (1/50): passageiro/motorista conversando com pedestre, sem manuseio.
