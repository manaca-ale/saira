# Camp 53 — exemplos da análise de erros a olho (16/11/2026)

Sem custo de API. Cada evento foi visto em folhas 2×2 com 4 a 9 frames da janela, às vezes com recorte e com as caixas do modelo desenhadas.

- Frames do conjunto oficial: `data/datasets/official/cam_picam001/<tp|fp|baseline>/<evento>/frames/`.
- Frames do holdout (`pi-inicial-v1`, repositório do Gabriel): `datasets/pi-inicial-v1/pi-cam-001/frames/<evento>/`.
- Para refazer uma folha: `python scripts/contact_sheet.py [--dataset pi-inicial-v1] --k 8 --no-dedupe [--bbox y0,x0,y1,x1] <evento>` (sai em `~/.saira-bench/sheets`, fora do repositório).
- "Detail atual" = `d25f_v1` (gemini-2.5-flash). "Recomendado" = `d38f_g3_low_low` (gemini-3.8-flash, prompt g3). Entre parênteses, a confiança.

Classes usadas: **veto do worker** (o modelo disse "sim" e a regra do bbox derrubou), **erro do modelo**, **rótulo** (o rótulo é discutível ou inconsistente), **ambíguo** (nem o operador vê o momento do descarte).

## Seis exemplos para o relatório

| # | Evento | Conjunto e rótulo | O que se vê | O que os modelos dizem | Classe |
|---|---|---|---|---|---|
| 1 | `evt-20260715_222047` (det 839bee07) | oficial, descarte confirmado | À noite (22:20), uma pessoa chega com um carrinho de mão cheio, para na borda do monte e sai com ele vazio. | Recomendado: "sim" (95) nas repetições; as caixas saem justas na borda do monte (0,91% e 0,69% da imagem) e o worker troca por "não" com confiança 0. Detail atual: "não" (90) numa repetição e "sim" (95) na outra. | veto do worker |
| 2 | `evt-20260717_201306` | oficial, falso ("Limpeza urbana") | Entre 20:12 e 20:15, no infravermelho, um caminhão de coleta e 4 ou 5 garis de uniforme refletivo retiram o monte. | Detail atual: "sim" (90). Recomendado: "não" (98). | acerto do modelo novo (erro do atual) |
| 3 | `evt-20260717_131804` (det 781cd838) | oficial, falso ("não percebemos o momento do descarte… catadores") | Um homem sem camisa aparece com um saco grande na borda do monte só no último frame (13:21:08). Não dá para dizer se deixa ou leva. | Todos confirmam (95 a 98); Decisions p = 0,806. | ambíguo |
| 4 | `evt-20260721_161751` | oficial, falso ("Descarte realizado no container") | Às 16:18:01, um senhor de branco esvazia um saco junto ao contêiner, no canto inferior esquerdo. | Recomendado: "sim" (98). | rótulo: há descarte, mas no contêiner; 3 eventos reais têm a mesma descrição do operador |
| 5 | `evt-20260722_114117` | oficial, "sem ocorrência" (rótulo do pipeline) | Às 11:39:30, uma carroça de grade com 3 ou 4 pessoas, carregada de baldes, canos e tábuas, está parada no monte; às 11:41:12 ela se foi e ficaram no lugar um quadro de madeira e um balde. | Gate de hoje não passa. Decisions p = 0,369 (passa nos três limiares); recomendado: "sim" (98). | rótulo: parece descarte real que a produção não viu |
| 6 | `evt-20260805_104753` | holdout, descarte confirmado | Carro preto parado ao fundo; entre 10:47:39 e 10:48:23 surge no monte um amontoado de folhas secas de palmeira, e duas pessoas voltam para o carro. O gesto cai entre dois frames. | Decisions p = 0,199: fica de fora por 0,001 no limiar 0,20. Os dois details confirmam quando recebem o evento. | limiar frágil do gate Decisions |

## Outros casos vistos

- `evt-20260715_085108` (oficial, real, det 2a7571b8): Kombi branca junto ao monte e homem de azul manuseando sacos. Recomendado diz "sim" (95); caixas de 0,25% a 0,99% da imagem conforme a repetição. **Veto do worker.**
- `evt-20260717_180936` (oficial, real, det 1d04290a): grupo de pessoas e um Fiat Uno com a tampa aberta às 18:11:13; o monte não muda nos frames amostrados. Nenhum gate passa (Decisions p = 0,134). **Rótulo com evidência fraca**; não é regressão da migração.
- `evt-20260715_073056` (oficial, falso, "pessoa remexendo lixo"): homem puxa uma haste de dentro do monte. Detail atual "sim" (85) nas duas repetições; recomendado "não" (85) nas duas. **Acerto do modelo novo.**
- `evt-20260716_012139` (oficial, falso, det 56e59ca0): de madrugada, uma pessoa estaciona um carrinho laranja no monte do fundo. Detail atual "sim" (95); recomendado "sim" (95 a 98) com caixas de 0,31% a 0,84%, vetado. **Ambíguo**; o veto esconde a resposta.
- `evt-20260722_115439` (oficial, "sem ocorrência"): uma mulher e depois um homem com um saco grande cheio de papel recolhem material do monte. Recomendado "sim" (85), quando o gate Decisions deixa passar. **Erro do modelo** (coleta lida como descarte).
- `evt-20260722_121140` (oficial, "sem ocorrência"): homem mexe no monte e uma caixa aberta aparece no último frame. Recomendado "sim" (95) via gate Decisions. **Ambíguo.**
- `evt-20260903_063641` (holdout, falso): enquadramento diferente; homem andando, moto e carro branco, sem descarte visível. Recomendado "sim" (85) com caixa minúscula ao fundo (0,47% e 0,29%), vetado. **Erro do modelo que o veto segura.**
- `evt-20260825_033529` (holdout, real): às 03:35:50 um caminhão chega de farol aceso e fica parado junto ao monte do fundo; não se vê descarga nos 15 frames. Detail atual "sim" (100); recomendado "não" (75 e 85). **Ambíguo**: o modelo novo exige ver o descarte.
- `evt-20260905_122758` (holdout, real): às 12:29:09 um homem sem camisa está abaixado no monte com um caixote ao lado; às 12:29:53 já saiu. Decisions p = 0,178 (fora no limiar 0,20); os details confirmam. **Limiar frágil.**
- `evt-20260724_084344` (holdout, real): "não" com confiança 0 numa repetição (veto) e "sim" (98) em outra, com a caixa da pessoa em 1,10%. **Veto do worker no limite de 1%.**

## Leitura

1. Das 3 detecções reais que a cascata recomendada perde no oficial, 2 são veto do worker e 1 não passa em gate nenhum, com evidência fraca nos frames. Em nenhuma o detail novo diz "não" a um descarte visível.
2. Os falsos que o detail novo deixa de confirmar são casos claros (limpeza urbana, pessoa remexendo). Os que ele ainda confirma são quase todos da classe "pessoa com saco ou carrinho junto ao monte", que o próprio operador descreve como "não percebemos o momento do descarte" (dets 132e7692, caebb65d, ed0b1eb9, eea58cf7, 781cd838, 78663961, 635f7de2, 617caa9b).
3. "Sem ocorrência" não é rótulo de operador: a justificativa é "classificado SEM descarte pelo pipeline". Pelo menos um desses eventos parece descarte real (exemplo 5). A taxa de "vazias" confirma pessoas mexendo no monte, não cena sem ninguém.
4. O rótulo do operador é inconsistente para descarte no contêiner (2 falsos e 3 reais com a mesma descrição).
5. No holdout, 4 confirmados ficam entre 0,178 e 0,199 no Decisions: o limiar 0,20 não tem folga.

## Não vistos a olho (folhas já geradas em `~/.saira-bench/sheets`)

- `evt-20260722_095851` e `evt-20260722_124935`: as duas "sem ocorrência" que a cascata recomendada confirma com o gate de hoje. A primeira o detail atual também confirma, nas duas repetições; a segunda o recomendado confirma em 2 de 3. Pelo texto do modelo, são pessoas revirando o monte (numa delas com carroça).
- `evt-20260724_130940` (p = 0,193) e `evt-20260803_094821` (p = 0,195): confirmados do holdout logo abaixo do limiar do Decisions.
