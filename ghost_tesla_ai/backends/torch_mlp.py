"""Reserved neural-network backend.

v0.1 intentionally does not install PyTorch on the Pi. The rest of the system talks
only to the backend interface, so a later patch can implement this class without
changing collection, storage, feature generation, dashboard APIs, or model history.
"""
from .base import ModelBackend
class TorchMLPBackend(ModelBackend):
    name='torch_mlp'
    def fit(self, X, y): raise RuntimeError('PyTorch backend is reserved for a later release')
    def predict(self, X): raise RuntimeError('PyTorch backend is reserved for a later release')
    def save(self, path): raise RuntimeError('PyTorch backend is reserved for a later release')
