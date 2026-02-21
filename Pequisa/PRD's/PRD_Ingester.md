--------------------------------------------------------------------------------
# Especificação Técnica: Serviço de Ingestão (Ingester v2.0)

**Projeto:** SAÍRA - Sistema de Alerta Inteligente para Resíduos e Autuações
**Módulo:** Camada de Ingestão (Edge-to-Cloud)
**Versão:** 2.0 (Arquitetura RTSP Direta)
**Status:** Especificação para Desenvolvimento

---

## 1. Visão Geral
O **Ingester Service** é um worker em Python responsável por conectar-se remotamente às câmeras de campo, capturar frames estáticos (snapshots) em intervalos definidos e enviá-los para o Data Lake (S3) para processamento assíncrono pela IA.

Diferente da versão anterior (baseada em emulação Android/ADB), esta versão conecta-se diretamente ao fluxo de vídeo da câmera via protocolo **RTSP**, trafegando através da conexão 4G provida pelo roteador Tenda 4G03.

## 2. Infraestrutura de Hardware (Origem)
O código deve ser agnóstico ao hardware, mas otimizado para as seguintes condições de borda:
*   **Conectividade:** 4G/LTE (Latência variável, possível perda de pacotes).
*   **Roteador:** Tenda 4G03 (Configurado como Cliente VPN ou Port Forwarding).
*   **Câmera:** Câmera IP Bullet (Padrão ONVIF/RTSP).
*   **Topologia de Rede:** O Ingester roda na AWS (VPC) e acessa as câmeras através de IPs privados (via Túnel VPN) ou IPs Públicos/DDNS (via Port Forwarding).

## 3. Requisitos Funcionais

### 3.1. Captura de Imagem (Snapshot)
*   **Protocolo:** O serviço deve consumir streams via `rtsp://`.
*   **Codec Suportado:** H.264 e H.265 (HEVC). *Nota: O H.265 é preferencial para economia de dados 4G.*
*   **Frequência:** Configurável por câmera (ex: a cada 5 minutos por padrão, ou a cada 30 segundos em modo "Alerta").
*   **Frame Drop:** O sistema deve descartar frames corrompidos ou incompletos causados por instabilidade do 4G.

### 3.2. Pré-processamento
*   **Redimensionamento:** Reduzir a resolução se necessário (ex: de 1080p para 640x640) para o modelo YOLO, economizando banda de upload para o S3, *caso a inferência não exija Full HD*. (Configurável).
*   **Sanity Check:** Verificar se a imagem não está totalmente preta (erro de sensor/IR), verde (erro de codec) ou cinza (falha de conexão).

### 3.3. Persistência e Mensageria
*   **Storage:** Upload da imagem validada para o bucket S3 `saira-landing-zone`.
*   **Notificação:** Após o upload, enviar mensagem para a fila SQS `saira-ingestion-queue` contendo a chave do objeto S3 e metadados.

---

## 4. Stack Tecnológico Sugerido

*   **Linguagem:** Python 3.10+
*   **Bibliotecas Principais:**
    *   `opencv-python-headless` (cv2): Para decodificação rápida de frames RTSP.
    *   `ffmpeg-python`: *Fallback* robusto caso o OpenCV falhe com streams H.265 corrompidos.
    *   `boto3`: SDK AWS para S3 e SQS.
    *   `pydantic`: Para validação de configuração e schemas de dados.
    *   `tenacity`: Para lógica de retries (tentativas) inteligentes na conexão 4G.

---

## 5. Estrutura de Dados e Configuração

### 5.1. Inventário de Câmeras (config/cameras.yaml)
O serviço deve carregar uma lista de câmeras. Em produção, isso virá do Banco de Dados, mas para o MVP, usar arquivo de configuração.

```yaml
cameras:
  - id: "cam_01_coque"
    rpa: 1
    # URL RTSP segue o padrão da marca (Ex: Intelbras/Genérica)
    # rtsp://user:password@ip:port/profile
    rtsp_url: "rtsp://admin:saira123@10.8.0.5:554/cam/realmonitor?channel=1&subtype=0"
    capture_interval_seconds: 300
    active: true

  - id: "cam_02_ilha_de_deus"
    rpa: 6
    rtsp_url: "rtsp://admin:saira123@10.8.0.6:554/live/ch0"
    capture_interval_seconds: 300
    active: true
5.2. Schema da Mensagem SQS (Output)
{
  "camera_id": "cam_01_coque",
  "timestamp": "2025-10-25T14:30:00Z",
  "s3_bucket": "saira-landing-zone",
  "s3_key": "raw/2025/10/25/cam_01_coque_143000.jpg",
  "metadata": {
    "rpa": 1,
    "source_resolution": "1920x1080"
  }
}

--------------------------------------------------------------------------------
6. Lógica de Implementação (Pseudocódigo)
def capture_cycle():
    cameras = load_config()
    
    for cam in cameras:
        try:
            # 1. Conexão (com Timeout agressivo para não travar no 4G)
            stream = connect_rtsp(cam.rtsp_url, timeout=10s)
            
            # 2. Captura (Grab single frame)
            # DICA: Limpar o buffer para não pegar frame velho em cache
            frame = stream.read()
            
            # 3. Validação
            if is_image_corrupted(frame):
                log_warning(f"Imagem corrompida na câmera {cam.id}")
                continue
                
            # 4. Upload S3
            s3_path = generate_path(cam.id)
            s3_client.upload(frame, s3_path)
            
            # 5. Notificar Fila
            sqs_client.send_message(camera_id=cam.id, path=s3_path)
            
        except ConnectionError:
            # Roteadores 4G caem. Logar e tentar na próxima.
            log_error(f"Falha de conexão {cam.id}")

--------------------------------------------------------------------------------
7. Pontos de Atenção para o Desenvolvedor
1. Buffer Lag: O OpenCV tende a acumular buffer de vídeo. Ao conectar, certifique-se de ler o último frame disponível, e não o primeiro do buffer, para garantir que a foto é do momento "agora".
2. RTSP via TCP vs UDP: Configure o cliente RTSP para tentar forçar TCP (interleaved). O 4G perde pacotes UDP, o que causa artefatos cinzas na imagem (smearing), atrapalhando a IA.
    ◦ No OpenCV: os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
3. Timeout é Lei: Nunca abra uma conexão sem timeout. Se o roteador Tenda perder o sinal 4G, o script pode ficar travado ("hang") para sempre esperando resposta. Use signal.alarm ou wrappers de timeout.
4. Concorrência: Para 10 câmeras, um loop sequencial simples (loop for) funciona. Se escalarmos para 50+, será necessário usar asyncio ou ThreadPoolExecutor para capturar em paralelo.
8. Definição de Pronto (DoD)
• [ ] Script conecta na câmera via URL RTSP.
• [ ] Frame é salvo localmente e é visível (não corrompido).
• [ ] Frame é enviado para o Bucket S3 correto.
• [ ] Dockerfile criado e otimizado (tamanho < 500MB).
• [ ] Logs estruturados implementados.

