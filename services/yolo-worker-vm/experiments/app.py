import cv2
from ultralytics import YOLO
from flask import Flask, Response, render_template, request
from werkzeug.utils import secure_filename
import os
from datetime import datetime

# --- Project Directory Configuration ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
LOG_FOLDER = os.path.join(BASE_DIR, 'logs')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(LOG_FOLDER, exist_ok=True)

# --- Flask App Initialization ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LOG_FOLDER'] = LOG_FOLDER

# --- Model Loading ---
model = YOLO('./final_saved_models/yolov8_2142.pt').to('cuda') 

# --- Configurações de Performance ---
FRAME_SKIP = 1  # Evita efeito de câmera lenta

# --- Global State Flags ---
terminate_flag = False

# --- Video Streaming Generator ---
def generate(file_path):
    global terminate_flag

    # --- Video Source Configuration ---
    if file_path == "camera":
        cap = cv2.VideoCapture(0)
        source_name = "camera_aovivo"
    elif file_path:
        cap = cv2.VideoCapture(file_path)
        base_name = os.path.basename(file_path)
        source_name = os.path.splitext(base_name)[0]
    else:
        return

    # --- Logging System Initialization ---
    timestamp_inicio = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"log_{source_name}_{timestamp_inicio}.txt"
    log_full_path = os.path.join(app.config['LOG_FOLDER'], log_filename)

    print(f"--> Gravando logs em: {log_full_path}")

    # --- Main Processing Loop ---
    with open(log_full_path, 'w', encoding='utf-8') as log_file:
        
        # Cabeçalho do log
        log_file.write(f"INICIO DA DETECCÃO: {datetime.now()}\n")
        log_file.write(f"FONTE: {source_name}\n")
        log_file.write("-" * 80 + "\n")
        log_file.write("DATA_HORA | CLASSE | CONFIANÇA | COORDENADAS (x1, y1, x2, y2)\n")
        log_file.write("-" * 80 + "\n")

        frame_count = 0
        last_annotated_frame = None 

        while cap.isOpened():
            if terminate_flag:
                break

            success, frame = cap.read()
            if not success:
                break
            
            frame_count += 1

            # Frame Skipping 
            if frame_count % FRAME_SKIP == 0:

                # --- YOLO Inference ---
                results = model(frame, verbose=False, device=0)
                
                # --- Data Logging Logic ---
                frame_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                # Loop pelas detecções para gravar no formato específico
                for box in results[0].boxes:
                    cls_id = int(box.cls[0])
                    class_name = model.names[cls_id]
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = box.xyxy[0].tolist() 
                    
                    log_line = (
                        f"{frame_timestamp} | "
                        f"{class_name:<15} | "
                        f"{conf:.4f} | "
                        f"[{x1:.1f}, {y1:.1f}, {x2:.1f}, {y2:.1f}]\n"
                    )
                    log_file.write(log_line)
                
                log_file.flush() # Garante a gravação no disco

                # Atualiza o quadro desenhado
                last_annotated_frame = results[0].plot()

            # --- Frame Streaming ---
            final_image = last_annotated_frame if last_annotated_frame is not None else frame
            
            ret, jpeg = cv2.imencode('.jpg', final_image)
            if not ret:
                break

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')

        # --- Cleanup & Finalization ---
        log_file.write("-" * 80 + "\n")
        log_file.write(f"FIM DA DETECCÃO: {datetime.now()}\n")

    cap.release()

# --- Route Definitions ---

@app.route('/video_feed')
def video_feed():
    file_path = request.args.get('file')
    return Response(
        generate(file_path),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/', methods=['GET', 'POST'])
def index():
    global terminate_flag
    terminate_flag = False
    file_path = None

    if request.method == 'POST':
        if request.form.get("camera") == "true":
            file_path = "camera"
        elif 'file' in request.files:
            file = request.files['file']
            if file.filename and file.filename.strip() != "":
                filename = secure_filename(file.filename)
                save_location = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_location)
                file_path = save_location

    return render_template('index.html', file_path=file_path)

@app.route('/stop', methods=['POST'])
def stop():
    global terminate_flag
    terminate_flag = True
    return "Process has been Terminated", 200

# --- Main Entry Point ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)