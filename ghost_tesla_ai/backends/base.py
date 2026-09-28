from __future__ import annotations
from abc import ABC, abstractmethod
class ModelBackend(ABC):
    name = 'base'
    @abstractmethod
    def fit(self, X, y): ...
    @abstractmethod
    def predict(self, X): ...
    @abstractmethod
    def save(self, path): ...
