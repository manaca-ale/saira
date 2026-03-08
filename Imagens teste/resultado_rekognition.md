# Resultado do Teste - AWS Rekognition (DetectLabels)

- Regiao: `us-east-1`
- Imagens processadas: **10**
- Imagens com lixo: **4**
- Imagens com infratores: **7**
- Rotulagem de imagem: **sim** (foram geradas copias com sufixo `_rotulada`)

## Resultado por imagem

| Imagem | Tem lixo | Lixo (label/conf) | Infratores | Top labels (ate 5) |
|---|---|---|---|---|
| 1.jpg | nao | - | 1 deteccoes (Pessoa) | Nature (100.0%), Outdoors (100.0%), Yard (100.0%), Picket Fence (98.13%), Backyard (97.92%) |
| 10.jpg | nao | - | - | Outdoors (99.98%), Nature (95.17%), City (94.14%) |
| 2.jpg | sim | Garbage (0.95) | 6 deteccoes (Carro, Pessoa) | Machine (97.38%), Wheel (97.38%), Car (95.8%), Transportation (95.8%), Vehicle (95.8%) |
| 3.jpg | nao | - | 2 deteccoes (Carro, Pessoa) | Person (97.61%), Car (97.45%), Transportation (97.45%), Vehicle (97.45%), Machine (92.01%) |
| 4.jpg | sim | Garbage (1.00) | 1 deteccoes (Pessoa) | Garbage (99.84%), Trash (99.84%), Person (85.35%) |
| 5.jpg | sim | Garbage (0.79) | - | Outdoors (84.76%), Garbage (78.83%) |
| 6.jpg | nao | - | - | Rubble (99.13%), Rock (95.37%) |
| 7.jpg | sim | Garbage (0.84) | 1 deteccoes (Pessoa) | Person (90.11%), Boat (87.03%), Transportation (87.03%), Vehicle (87.03%), Garbage (84.4%) |
| 8.jpg | nao | - | 3 deteccoes (Carro, Pessoa) | Outdoors (99.98%), City (99.15%), Nature (97.62%), Car (95.47%), Transportation (95.47%) |
| 9.jpg | nao | - | 5 deteccoes (Carro, Moto, Pessoa) | Outdoors (99.97%), City (99.78%), Nature (95.6%), Motorcycle (95.29%), Transportation (95.29%) |

## Imagens rotuladas geradas

- `1_rotulada.jpg`
- `10_rotulada.jpg`
- `2_rotulada.jpg`
- `3_rotulada.jpg`
- `4_rotulada.jpg`
- `5_rotulada.jpg`
- `6_rotulada.jpg`
- `7_rotulada.jpg`
- `8_rotulada.jpg`
- `9_rotulada.jpg`