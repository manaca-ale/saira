import os
import shutil
import pandas as pd
import matplotlib.pyplot as plt
import torch
from ultralytics import YOLO

# ==========================================
# CONFIGURATION FIELDS - SETUP
# ==========================================

# Field to name your model (Differentiates this run from others)
custom_model_name = "yolov8_2142"

# Field to load your custom dataset
dataset_yaml_path = "C:/Gabriel/Projetos/dataset/LitterDataset_2142/data.yaml" 

# Configuration for the base model (COCO pretrained)
base_model_weights = "yolov8n.pt" 

# Directory to store the organized, renamed model files
models_storage_dir = "final_saved_models"

# ==========================================
# TRAINING EXECUTION
# ==========================================

def train_model():
    """
    Initializes and trains the YOLOv8 model, then extracts and renames the weights.
    """
    print(f"--- Starting training for: {custom_model_name} ---")
    
    if torch.cuda.is_available():
        print(f"✅ GPU DETECTED: {torch.cuda.get_device_name(0)}")
    else:
        print("⚠️ WARNING: GPU not detected. Training will run on CPU (Slow).")
    
    model = YOLO(base_model_weights)
    
    # Train the model
    results = model.train(
        data=dataset_yaml_path,
        epochs=100,                
        imgsz=640,  
        batch= 8,    
        optimizer= 'Adam',          
        project="training_runs",  
        name=custom_model_name,   
        exist_ok=True ,
        device=0,
        workers=8            
    )
    
    print(f"--- Training complete. Processing model file... ---")
    
    source_weights_path = os.path.join("training_runs", custom_model_name, "weights", "best.pt")
    
    if not os.path.exists(models_storage_dir):
        os.makedirs(models_storage_dir)
        
    destination_weights_path = os.path.join(models_storage_dir, f"{custom_model_name}.pt")
    
    if os.path.exists(source_weights_path):
        shutil.copy(source_weights_path, destination_weights_path)
        print(f"SUCCESS: Model saved and renamed to: {destination_weights_path}")
    else:
        print(f"ERROR: Could not find trained weights at {source_weights_path}")

    return model

# ==========================================
# CUSTOM GRAPHICS GENERATION
# ==========================================

def generate_custom_graphics(model_name):
    """
    Parses the training CSV log and generates organized matplotlib charts.
    """
    print("--- Generating custom graphics ---")
    
    results_path = os.path.join("training_runs", model_name, "results.csv")
    
    if not os.path.exists(results_path):
        print(f"Error: Could not find results file at {results_path}")
        return

    df = pd.read_csv(results_path)
    df.columns = [c.strip() for c in df.columns]

    output_dir = os.path.join("graphics_results", f"{model_name}_analysis")
    os.makedirs(output_dir, exist_ok=True)

    metrics = [
        ('train/box_loss', 'val/box_loss', 'Box Loss'),
        ('train/cls_loss', 'val/cls_loss', 'Class Loss'),
        ('train/dfl_loss', 'val/dfl_loss', 'DFL Loss'),
        ('metrics/precision(B)', None, 'Precision'),
        ('metrics/recall(B)', None, 'Recall'),
        ('metrics/mAP50(B)', 'metrics/mAP50-95(B)', 'mAP Metrics')
    ]

    for metric_data in metrics:
        plt.figure(figsize=(10, 6))
        
        if metric_data[0] in df.columns:
            plt.plot(df['epoch'], df[metric_data[0]], label=metric_data[0], marker='o', markersize=2)
        
        if metric_data[1] and metric_data[1] in df.columns:
            plt.plot(df['epoch'], df[metric_data[1]], label=metric_data[1], marker='x', markersize=2)
            
        plt.title(f"{metric_data[2]} over Epochs - {model_name}")
        plt.xlabel("Epoch")
        plt.ylabel("Value")
        plt.legend()
        plt.grid(True)
        
        filename = f"{metric_data[2].replace(' ', '_').lower()}.png"
        save_path = os.path.join(output_dir, filename)
        plt.savefig(save_path)
        plt.close()
        
    print(f"--- Graphics saved to: {output_dir} ---")

# ==========================================
# MAIN EXECUTION FLOW
# ==========================================

if __name__ == '__main__':
    train_model()
    generate_custom_graphics(custom_model_name)