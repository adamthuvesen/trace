# Embedding backend

Set **`EMBEDDING_BACKEND`** to `onnx` for int8 ONNX inference (the default,
faster on CPU) or `torch` for the PyTorch path. Both load the same embedding
model; only the runtime differs.
