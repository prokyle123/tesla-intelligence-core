from __future__ import annotations
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor
from .base import ModelBackend

class SklearnHistGBBackend(ModelBackend):
    name = 'sklearn_histgb'
    def __init__(self, model=None):
        self.model = model or HistGradientBoostingRegressor(max_iter=180, learning_rate=0.07, max_leaf_nodes=31, l2_regularization=0.1, random_state=42)
    def fit(self, X, y): self.model.fit(X, y); return self
    def predict(self, X): return self.model.predict(X)
    def save(self, path): joblib.dump({'backend':self.name,'model':self.model}, path)
    @classmethod
    def load(cls, path):
        obj = joblib.load(path); return cls(obj['model'])
