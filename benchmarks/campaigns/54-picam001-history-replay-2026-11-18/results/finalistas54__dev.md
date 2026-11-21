# Campanha 54 — funis finalistas (congelado em 21/11/2026 às 02:30, antes de qualquer medição no conjunto de avaliação)

Escrito pelo turno `noiteB` (missão 7). Vale até o Alexandre aprovar ou trocar os finalistas; a medição final (missão 10) só roda depois do ok dele. Números do conjunto de desenvolvimento (`pass`: 32 detecções confirmadas, 61 rejeitadas), tirados de `funnels54__dev.txt` (script `scripts/funnels54.py`).

## Regra de escolha

Custo por evento no máximo igual ao de hoje (limite +20%), o máximo possível das confirmadas mantidas, sem aumentar os alertas falsos. Custo e latência em modo padrão (sem Flex), com o detail a preço do Vertex.

## Os seis funis medidos

| Funil (gate + detail) | Confirmadas | Rejeitadas | Alertas por 1.000 eventos | Parte S0: descarte provável / falso / indefinido | Custo por evento (detail no Vertex) |
|---|---|---|---|---|---|
| hoje refeito (2.5-flash-lite + 2.5-flash) | 21 de 32 | 26 de 61 | 14,1 | 3,0 / 2,2 / 0,7 | −54% [−57 a −50] |
| 3.1-flash-lite + 2.5-flash | 26 de 32 | 30 de 61 | 28,8 | 6,3 / 8,2 / 5,7 | −41% [−47 a −35] |
| Nova Lite + 2.5-flash | 26 de 32 | 26 de 61 | 19,5 | 1,8 / 4,9 / 3,7 | −50% [−55 a −44] |
| 2.5-flash-lite + 3.8-flash | 19 de 32 | 21 de 61 | 14,4 | 3,7 / 2,2 / 1,5 | −43% [−47 a −36] |
| **B: 3.1-flash-lite + 3.8-flash** | 25 de 32 | 23 de 61 | 27,7 | 5,1 / 8,2 / 6,3 | −21% [−30 a −11] |
| **A: Nova Lite + 3.8-flash** | 25 de 32 | 19 de 61 | 15,9 | 1,8 / 1,8 / 4,3 | −31% [−38 a −21] |

O custo é contra o de hoje em produção (US$ 0,001327 por evento, sem filtro). A faixa é só a margem de 95% do disparo em cenas sem ocorrência (S0). Com o detail a preço do AI Studio, A fica em −56% e B em −48%. A parte S0 vem da leitura a olho de um revisor só (missão 6); S0 = cenas em que o gate de produção não disparou. Diferença de 1 ou 2 detecções é ruído (o gate de hoje refeito varia de 22 a 24 das 32 entre rodadas).

Os funis com o detail de hoje (`gemini-2.5-flash`) ficam só como referência: é o modelo que está saindo de linha, motivo desta migração. O gate de hoje com o 3.8-flash perde confirmadas (19 de 32) e também sai de linha.

## Finalistas

**A — Nova Lite no gate, gemini-3.8-flash no detail (escolhido pela regra).** Mantém 25 das 32 confirmadas (hoje refeito: 21), deixa passar 19 das 61 rejeitadas (hoje refeito: 26), 15,9 alertas por 1.000 eventos (hoje refeito: 14,1) e custa 31% menos que hoje. Nos alertas vindos de cenas sem rótulo, os falsos prováveis não sobem (1,8 por 1.000, contra 2,2 hoje); os indefinidos sobem (4,3 contra 0,7).

**B — gemini-3.1-flash-lite no gate, gemini-3.8-flash no detail (alternativa; fere a cláusula dos alertas falsos).** Mesmas 25 confirmadas, 23 rejeitadas, custo 21% menor que hoje, tudo dentro do Google. Levanta quase o dobro de alertas (27,7 por 1.000): acha mais descarte que hoje passa em branco (5,1 por 1.000, contra 1,8 do A) e cobra isso em falsos (8,2 contra 1,8). Entra como finalista porque a escolha entre detectar mais e alertar menos é do Alexandre, e porque não exige mandar imagens para a AWS.

## Configuração congelada

- **Filtro (os dois):** Decisions com a pergunta `wl_v2` sozinha no pedido (conjunto `q5` de `qsets54.py`), 5 frames em resolução baixa; o evento segue para o gate se a nota for ≥ 0,30.
- **Gate do A:** braço `nvl_v1p_low_ctx` (`run_gate54_bedrock.py`): Amazon Nova Lite no Bedrock, prompt `v1p`, 5 frames, mídia `low`, aviso da janela anterior como a produção manda; dispara com `new_litter` verdadeiro e confiança ≥ 85.
- **Gate do B:** braço `g31l_v1p_min_low_ctx` (`run_gate54.py`): `gemini-3.1-flash-lite`, prompt `v1p`, pensamento `minimal`, mídia `low`, aviso da janela anterior; dispara com `new_litter` verdadeiro e confiança ≥ 85.
- **Detail (os dois):** braço `d38f_g3_low_low` (`run_detail54.py`): `gemini-3.8-flash`, prompt `g3`, pensamento `low`, mídia `low`, janela inteira (mediana 32 quadros, máximo 44), aviso da janela anterior, sem `horario_local`, veredito final com o veto de grounding do worker.
- **Modo:** padrão, sem Flex. Latência p90 medida: gate Nova 4,0 s, gate 3.1-flash-lite 3,0 s (painel, rodada em modo padrão), detail 13,8 s.

Nada disso muda entre agora e a medição final. Se algum parâmetro precisar mudar, escreve-se aqui antes, com data e motivo.

## Régua proposta para a medição final (a confirmar com o Alexandre)

No conjunto de avaliação, com o funil de controle (gate e detail de hoje) refeito nos mesmos eventos, um finalista passa se: (1) mantém pelo menos as confirmadas do controle menos 2; (2) custa por evento no máximo o de hoje mais 20%, com o detail a preço do Vertex; (3) não deixa passar mais rejeitadas que o controle. Para o B, registrar também os alertas por 1.000 eventos e dizer quantas vezes o de hoje.

## O que pode dar errado

1. **Nova Lite manda imagens para a AWS.** É um segundo fornecedor e uma decisão de contrato e de dados, não de engenharia. O Nova só serve atrás do filtro.
2. **O detail foi medido no AI Studio.** No Vertex o 3.8-flash custa o dobro por chamada (US$ 0,0163) e o esquema entra como tokens de entrada; a conta acima já usa o preço do Vertex, mas a qualidade no Vertex não foi medida.
3. **O replay do detail de hoje só concorda com a produção em 75% dos eventos** e a causa não foi isolada (falta o teste de US$ 0,40 no Vertex). Todo número de detail carrega essa incerteza.
4. **O B dobra os alertas.** Quatro em cada dez alertas a mais vindos de cenas sem rótulo são falsos (catador, manuseio, passagem); quem valida vai sentir.
5. **A divisão dos alertas sem rótulo é leitura do agente**, em folhas reduzidas e sem cegamento: 18 dos 54 ficaram indefinidos. O rótulo do operador pode mudar a comparação entre A e B.
6. **Amostra pequena:** A e B empatam nas confirmadas (25 e 25) e a diferença nas rejeitadas (19 e 23) está perto do ruído. Um S2C ficou sem veredito do detail de hoje e 7 janelas S0 não estão em disco.
7. **Uma câmera, um período** (pi-cam-001, julho a setembro de 2026). À noite os alertas sem rótulo são quase todos falsos (14 de 20); nenhuma regra por horário foi testada.
8. **Vida dos modelos:** o 3.1-flash-lite fica no Vertex até 07/05/2027 ou depois; o Nova Lite não tem data anunciada; o 3.8-flash precisa ser conferido na página de depreciação do Vertex antes do rollout.
