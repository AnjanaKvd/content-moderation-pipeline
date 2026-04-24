import time
import os
import logging
from typing import Optional, List, Dict
from onnxruntime import InferenceSession
from transformers import AutoTokenizer
import numpy as np
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class ToxicityClassifier:
    def __init__(self, model_path: str, tokenizer_path: str, max_length: int = 512):
        start_time = time.time()
        
        # Load ONNX session
        self.session = InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_path)
        self.max_length = max_length
        
        # tox-bert outputs 6 labels (toxic, severe_toxic, obscene, threat, insult, identity_hate)
        # We will use label 0 (toxic) with a sigmoid threshold.
        
        self.input_names = [i.name for i in self.session.get_inputs()]
        self.output_names = [o.name for o in self.session.get_outputs()]
        
        logger.info(f"Model input names: {self.input_names}")
        logger.info(f"Model output names: {self.output_names}")
        
        self.load_time_ms = (time.time() - start_time) * 1000
        logger.info(f"Model loaded in {self.load_time_ms:.2f} ms")

    def _sigmoid(self, x):
        return 1 / (1 + np.exp(-x))

    def predict(self, text: str) -> dict:
        start_time = time.time()
        try:
            tokens = self.tokenizer(
                text,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np"
            )
            
            inputs = {name: tokens[name].astype(np.int64) for name in self.input_names if name in tokens}
            
            logits = self.session.run(self.output_names, inputs)[0][0]
            probs = self._sigmoid(logits)
            
            toxic_prob = float(probs[0])
            non_toxic_prob = 1.0 - toxic_prob
            
            if toxic_prob > 0.5:
                label = "toxic"
                confidence = toxic_prob
            else:
                label = "non_toxic"
                confidence = non_toxic_prob
            
            inference_time_ms = (time.time() - start_time) * 1000
            
            return {
                "label": label,
                "confidence": float(round(confidence, 4)),
                "scores": {
                    "toxic": float(round(toxic_prob, 4)),
                    "non_toxic": float(round(non_toxic_prob, 4))
                },
                "inference_time_ms": float(round(inference_time_ms, 2))
            }
        except Exception as e:
            logger.error(f"Inference error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Inference failed")

    def predict_batch(self, texts: List[str]) -> List[dict]:
        start_time = time.time()
        try:
            tokens = self.tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="np"
            )
            
            inputs = {name: tokens[name].astype(np.int64) for name in self.input_names if name in tokens}
            
            logits = self.session.run(self.output_names, inputs)[0]
            probs = self._sigmoid(logits)
            
            toxic_probs = probs[:, 0]
            non_toxic_probs = 1.0 - toxic_probs
            
            inference_time_ms = (time.time() - start_time) * 1000
            
            results = []
            for i in range(len(texts)):
                toxic_prob = float(toxic_probs[i])
                non_toxic_prob = float(non_toxic_probs[i])
                
                if toxic_prob > 0.5:
                    label = "toxic"
                    confidence = toxic_prob
                else:
                    label = "non_toxic"
                    confidence = non_toxic_prob
                
                results.append({
                    "label": label,
                    "confidence": float(round(confidence, 4)),
                    "scores": {
                        "toxic": float(round(toxic_prob, 4)),
                        "non_toxic": float(round(non_toxic_prob, 4))
                    },
                    "inference_time_ms": float(round(inference_time_ms / len(texts), 2))
                })
            return results
            
        except Exception as e:
            logger.error(f"Batch inference error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Batch inference failed")

_classifier: Optional[ToxicityClassifier] = None

def get_classifier() -> ToxicityClassifier:
    global _classifier
    if _classifier is None:
        model_path = os.getenv("MODEL_PATH", "./models/toxic-bert-onnx/model.onnx")
        tokenizer_path = os.getenv("TOKENIZER_PATH", "./models/toxic-bert-onnx/")
        max_length = int(os.getenv("MAX_SEQUENCE_LENGTH", "512"))
        
        _classifier = ToxicityClassifier(
            model_path=model_path,
            tokenizer_path=tokenizer_path,
            max_length=max_length
        )
    return _classifier
