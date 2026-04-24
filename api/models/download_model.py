import os
from transformers import AutoTokenizer
from optimum.onnxruntime import ORTModelForSequenceClassification

def download_and_export_model():
    MODEL_ID = "unitary/toxic-bert"
    SAVE_PATH = "./models/toxic-bert-onnx"

    print(f"Downloading {MODEL_ID} and exporting to ONNX...")
    
    # Load model and export
    model = ORTModelForSequenceClassification.from_pretrained(MODEL_ID, export=True)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)

    # Save
    print(f"Saving to {SAVE_PATH}...")
    model.save_pretrained(SAVE_PATH)
    tokenizer.save_pretrained(SAVE_PATH)

    # Confirm files
    onnx_path = os.path.join(SAVE_PATH, "model.onnx")
    if os.path.exists(onnx_path):
        size = os.path.getsize(onnx_path) / (1024 * 1024)
        print(f"Success! model.onnx exists ({size:.2f} MB)")
    else:
        print("Error: model.onnx not found after export.")

if __name__ == "__main__":
    download_and_export_model()
