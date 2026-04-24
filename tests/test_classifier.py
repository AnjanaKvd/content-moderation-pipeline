import pytest
import numpy as np
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../api')))
from models.classifier import ToxicityClassifier

# We'll need a mock or actual downloaded model to run these tests locally.
# Assuming the model has been downloaded via download_model.py
MODEL_PATH = "./models/toxic-bert-onnx/model.onnx"
TOKENIZER_PATH = "./models/toxic-bert-onnx/"

@pytest.fixture(scope="module")
def classifier():
    return ToxicityClassifier(model_path=MODEL_PATH, tokenizer_path=TOKENIZER_PATH)

def test_model_loads(classifier):
    assert classifier.load_time_ms > 0

def test_toxic_comment(classifier):
    result = classifier.predict("I hate you and want to hurt you")
    assert result["label"] == "toxic"
    assert result["confidence"] > 0.7
    assert "toxic" in result["scores"]
    assert "non_toxic" in result["scores"]

def test_clean_comment(classifier):
    result = classifier.predict("Have a wonderful day!")
    assert result["label"] == "non_toxic"
    assert result["confidence"] > 0.7

def test_predict_returns_all_fields(classifier):
    result = classifier.predict("Test")
    assert "label" in result
    assert "confidence" in result
    assert "scores" in result
    assert "inference_time_ms" in result

def test_batch_predict(classifier):
    comments = [
        "I hate you",
        "Have a great day",
        "You are terrible",
        "Hello world",
        "Another clean one"
    ]
    results = classifier.predict_batch(comments)
    assert len(results) == 5
    assert results[0]["label"] == "toxic"
    assert results[1]["label"] == "non_toxic"

def test_empty_string_handling(classifier):
    result = classifier.predict("")
    # toxic-bert usually treats empty string as non-toxic with high confidence
    assert result["label"] == "non_toxic"
