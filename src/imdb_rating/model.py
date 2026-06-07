import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin


class ConstantRatingModel(BaseEstimator, ClassifierMixin):
    """Dummy baseline: always predicts the same rating.

    Validates the full training -> registry -> serving loop without involving
    any real learning. Gets replaced by a real model in a later iteration.
    """

    def __init__(self, value: int = 8):
        self.value = value

    def fit(self, X, y=None):
        self.classes_ = np.array([self.value])
        return self

    def predict(self, X):
        n = len(X) if hasattr(X, "__len__") else 1
        return np.full(n, self.value, dtype=int)
