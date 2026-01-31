# Analise: Loop principal parado enquanto health check continua

Data da analise: 31/01/2026.

## Sintomas observados
- O ultimo "Ciclo iniciado" no log foi o `cycle_id=254` em 31/01/2026 01:18:56.
- A partir de ~01:22:01 aparecem timeouts longos de ADB (ex.: `dumpsys battery`, `am force-stop`, `get-state`).
- O arquivo `health.jsonl` continua sendo atualizado periodicamente, indicando que o health loop segue ativo.
- Os artifacts de erro dos ciclos 252/253 mostram o aparelho no HOME; `window.txt` mostra foco no launcher.
- `logcat.txt` dos ciclos 252/253 mostra travamento/instabilidade do app e OOM no `com.xm.csee`.

## Hipotese principal
O loop principal ficou bloqueado dentro do ciclo 254 ao executar uma chamada ADB lenta/pendurada.
Como o health check roda em outra thread, ele continuou funcionando, criando a impressao de que "o sistema ainda esta rodando".

## Evidencias diretas
- `ingester.log`:
  - Ultimo ciclo iniciado: `cycle_id=254` em 01:18:56.
  - Timeouts longos de ADB logo depois (~01:22:01), indicando comando bloqueado.
- `health.jsonl`:
  - Continua gerando eventos (ex.: 09:49), logo a thread de health esta viva.
- `cycle_252_artifacts` / `cycle_253_artifacts`:
  - Screenshot no HOME; foco do `WindowManager` no launcher.
  - `logcat` mostra OOM do `com.xm.csee`.

## Porque o loop nao "tentou mais"
O loop principal so reinicia ao finalizar o ciclo atual. Se uma chamada ADB fica presa, o ciclo nao termina e o proximo nunca inicia.
O backoff e as tentativas sao aplicados somente depois que uma excecao sobe e o ciclo finaliza.

## Como verificar agora (passos rapidos)
Sem `rg` instalado, use:

1) Ultimos ciclos e timeouts:
```
Select-String -Path C:\saira\services\ingester\logs\ingester.log -Pattern "Ciclo iniciado|ADB timeout duration" |
  Select-Object -Last 20
```

2) Health loop ativo:
```
Get-Content -Tail 5 C:\saira\services\ingester\logs\health.jsonl
```

3) Ultimos ciclos gravados:
```
Get-Content -Tail 3 C:\saira\services\ingester\logs\cycles.jsonl
```

## Opcoes para consertar (prioridade sugerida)

### Opcao A: Watchdog de ciclo (evita travar indefinidamente)
Adicionar um timeout global por ciclo. Se exceder X segundos, o loop aborta o ciclo atual e inicia outro.

Impacto:
- Evita travas permanentes quando ADB nao responde.

### Opcao B: Timeout + retry mais agressivo em ADB critico
Para comandos de alto risco (ex.: `am force-stop`, `dumpsys battery`), habilitar `retry_on_timeout=True`
ou reduzir o timeout e re-tentar com backoff curto.

Impacto:
- Menos travas longas no loop.
- Pode aumentar carga de ADB.

### Opcao C: Separar health e capture com isolamento
Se o ciclo principal travar, um supervisor (ou outro thread) pode reiniciar o processo.

Impacto:
- Mais resiliencia.
- Requer ajuste de arquitetura.

### Opcao D: Reforcar recuperacao do app
Quando detectar foco no launcher ou OOM do app, reiniciar o app antes de seguir:
- Reabrir app se foco != `com.xm.csee`.
- Limpar cache/force-stop + relaunch ao detectar OOM.

Impacto:
- Ajuda quando o app entra em estado instavel.

## Proxima acao recomendada
Implementar Opcao A (watchdog de ciclo) + Opcao B (retry em ADB critico), pois sao pequenas mudancas
que evitam o loop travar e nao impactam o fluxo principal.

