from __future__ import annotations
import joblib
from sklearn.impute import SimpleImputer
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

class SklearnMLPBackend:
    name='sklearn_mlp_experimental'
    def __init__(self,model=None):
        self.model=model or Pipeline([
            ('impute',SimpleImputer(strategy='median')),
            ('scale',StandardScaler()),
            ('mlp',MLPRegressor(hidden_layer_sizes=(64,32),activation='relu',solver='adam',alpha=0.001,
                                early_stopping=True,validation_fraction=0.15,n_iter_no_change=18,max_iter=240,
                                random_state=42,learning_rate_init=0.001))
        ])
    def fit(self,X,y): self.model.fit(X,y); return self
    def predict(self,X): return self.model.predict(X)
    def save(self,path): joblib.dump(self.model,path)
    @classmethod
    def load(cls,path): return cls(joblib.load(path))
