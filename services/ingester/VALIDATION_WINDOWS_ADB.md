# Validação do Ambiente Windows para Ingester Local com ADB

Este documento descreve os passos para validar que o ambiente Windows está pronto para rodar o serviço `ingester` localmente via Docker, com o Android Debug Bridge (ADB) rodando no host.

### Checklist de Validação do Ambiente

- [ ] Docker Desktop está instalado e em execução.
- [ ] Android Debug Bridge (ADB) está instalado e configurado no PATH do sistema.
- [ ] Celular Android está com "Opções do desenvolvedor" e "Depuração USB" ativadas.
- [ ] Celular Android está conectado via USB ao computador.
- [ ] A autorização de depuração USB foi concedida no celular.
- [ ] O dispositivo é reconhecido pelo ADB no host Windows com o status `device`.

### Comandos de Verificação (PowerShell)

Execute os seguintes comandos no seu terminal PowerShell para confirmar a configuração:

1.  **Verificar Docker:**
    *   Confirma que o Docker está instalado e o daemon está respondendo.
    ```powershell
    docker --version && docker ps
    ```

2.  **Verificar ADB:**
    *   Confirma que o ADB está instalado e acessível pelo terminal.
    ```powershell
    adb --version
    ```

3.  **Verificar Dispositivo Conectado:**
    *   Lista os dispositivos Android conectados. Você deve ver o serial do seu dispositivo com o status `device`.
    ```powershell
    adb devices
    ```
    *Saída esperada:*
    ```
    List of devices attached
    <serial_number>    device
    ```

### Erros Comuns e Soluções

1.  **`'adb' não é reconhecido como um comando`**
    *   **Causa:** A pasta de ferramentas do Android SDK (`platform-tools`) não está na variável de ambiente `Path` do sistema.
    *   **Solução:** Adicione o caminho completo da pasta `platform-tools` (ex: `C:\Users\<seu-usuario>\AppData\Local\Android\sdk\platform-tools`) à variável de ambiente `Path` e reinicie o terminal.

2.  **Dispositivo listado como `unauthorized`**
    *   **Causa:** A permissão de depuração USB não foi concedida no celular para o computador conectado.
    *   **Solução:** Desconecte e reconecte o cabo USB. Uma caixa de diálogo de autorização aparecerá na tela do celular. Marque a opção "Sempre permitir deste computador" e toque em "Permitir".

3.  **Nenhum dispositivo listado por `adb devices`**
    *   **Causa:** Problema com o cabo USB, drivers do dispositivo no Windows, ou a opção "Depuração USB" está desativada no celular.
    *   **Solução:**
        1.  Tente usar um cabo USB ou porta diferente.
        2.  No celular, vá para "Opções do desenvolvedor" e confirme que a "Depuração USB" está ativada.
        3.  Instale os drivers USB OEM para o seu dispositivo no Windows.
