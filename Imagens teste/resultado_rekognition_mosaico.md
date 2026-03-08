# Resultado do Teste - AWS Rekognition com Mosaico 2x2

- Regiao: `us-east-1`
- Modo: `rekognition_mosaic_2x2`
- Imagens processadas: **10**
- Batches processados: **3**
- Imagens com lixo: **0**
- Imagens com infratores: **5**
- Rotulagem de imagem: **sim** (copias com sufixo `_mosaico_rotulada`)

## Metadados dos batches

- Batch 0: imagens=['1.jpg', '2.jpg', '3.jpg', '4.jpg'] | mosaico=1920x1440 | bytes=668557 | q=90 | downscale=1.0 | fallback=True
- Batch 1: imagens=['5.jpg', '6.jpg', '7.jpg', '8.jpg'] | mosaico=1920x1440 | bytes=679338 | q=90 | downscale=1.0 | fallback=False
- Batch 2: imagens=['9.jpg', '10.jpg'] | mosaico=1920x1440 | bytes=505579 | q=90 | downscale=1.0 | fallback=False

## Resultado por imagem

| Imagem | Tem lixo | Lixo (label/conf) | Infratores | Exemplo bbox lixo mapeada |
|---|---|---|---|---|
| 1.jpg | nao | - | - | - |
| 2.jpg | nao | - | 6 deteccoes (Carro, Pessoa) | - |
| 3.jpg | nao | - | 2 deteccoes (Carro, Pessoa) | - |
| 4.jpg | nao | - | - | - |
| 5.jpg | nao | - | - | - |
| 6.jpg | nao | - | - | - |
| 7.jpg | nao | - | 2 deteccoes (Pessoa) | - |
| 8.jpg | nao | - | 1 deteccoes (Carro) | - |
| 9.jpg | nao | - | 2 deteccoes (Moto, Pessoa) | - |
| 10.jpg | nao | - | - | - |

## Imagens rotuladas geradas

- `1_mosaico_rotulada.jpg`
- `2_mosaico_rotulada.jpg`
- `3_mosaico_rotulada.jpg`
- `4_mosaico_rotulada.jpg`
- `5_mosaico_rotulada.jpg`
- `6_mosaico_rotulada.jpg`
- `7_mosaico_rotulada.jpg`
- `8_mosaico_rotulada.jpg`
- `9_mosaico_rotulada.jpg`
- `10_mosaico_rotulada.jpg`