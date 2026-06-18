"""Publish a dummy (constant) rating model to the W&B registry.

This is the first iteration of the training pipeline. The model itself is
trivial - it always predicts the same rating - and its only purpose is to
exercise the full training -> registry -> serving loop end-to-end. Real
featurization and learning come in a follow-up PR.
"""
from pathlib import Path
from sklearn.pipeline import Pipeline
import json
import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split, GridSearchCV, KFold
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import FunctionTransformer
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import ElasticNet
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


from imdb_rating.model import ConstantRatingModel
from imdb_rating.registry import publish

WANDB_ENTITY = "mlprod-obli"
WANDB_PROJECT = "imdb-rating"
WANDB_ARTIFACT = "imdb-rating-model"
WANDB_ALIAS = "production"
DUMMY_VALUE = 8


def train_elastic_net():
    
    # ============================================================
    # 1. Cargar dataset
    # ============================================================

    DATA_PATH = Path(__file__).parent / "training_dataset.json"

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    df = pd.DataFrame(data)

    print("Shape original:", df.shape)
    print(df.head())


    # ============================================================
    # 2. Filtrar registros sin director
    # ============================================================

    def has_director(x):
        return isinstance(x, list) and len(x) > 0

    df = df[df["directors"].apply(has_director)].copy()

    print("Shape luego de filtrar sin director:", df.shape)


    # ============================================================
    # 3. Limpieza / feature engineering básico
    # ============================================================

    # Convertimos listas a strings separados por "|"
    # Esto permite usar CountVectorizer como un one-hot multi-label.
    df["directors_text"] = df["directors"].apply(lambda xs: "|".join(xs) if isinstance(xs, list) else "")
    df["cast_text"] = df["main_cast"].apply(lambda xs: "|".join(xs) if isinstance(xs, list) else "")

    # reviews parece ser una variable numérica ya procesada.
    # La dejamos como numérica e imputamos faltantes luego.
    df["reviews"] = pd.to_numeric(df["reviews"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["votes"] = pd.to_numeric(df["votes"], errors="coerce")

    # votos suele tener una distribución muy sesgada.
    # Conviene usar log1p(votes).
    df["log_votes"] = np.log1p(df["votes"])

    # Target
    target = "imdb_rating"

    # Features a usar
    features = [
        "title",
        "year",
        "log_votes",
        "reviews",
        "directors_text",
        "cast_text",
    ]

    X = df[features]
    y = df[target]


    # ============================================================
    # 4. Train / test split
    # ============================================================

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.2,
        random_state=42
    )

    print("Train:", X_train.shape)
    print("Test:", X_test.shape)


    # ============================================================
    # 5. Preprocesamiento
    # ============================================================

    numeric_features = ["year", "log_votes", "reviews"]

    numeric_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler())
        ]
    )

    # Para título usamos TF-IDF porque es texto libre.
    title_transformer = TfidfVectorizer(
        max_features=1000,
        ngram_range=(1, 2),
        lowercase=True
    )

    # Para directores y actores usamos CountVectorizer con separador "|".
    # Esto funciona como one-hot/multi-hot encoding.
    people_vectorizer = CountVectorizer(
        tokenizer=lambda x: x.split("|"),
        token_pattern=None,
        lowercase=False,
        binary=True,
        min_df=2
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", numeric_transformer, numeric_features),
            ("title_tfidf", title_transformer, "title"),
            ("directors_ohe", people_vectorizer, "directors_text"),
            ("cast_ohe", people_vectorizer, "cast_text"),
        ],
        remainder="drop"
    )


    # ============================================================
    # 6. Modelo Elastic Net
    # ============================================================

    elastic_net = ElasticNet(
        max_iter=20000,
        random_state=42
    )

    model = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("regressor", elastic_net)
        ]
    )


    # ============================================================
    # 7. Búsqueda de hiperparámetros
    # ============================================================

    param_grid = {
        "regressor__alpha": [0.0001, 0.001, 0.01, 0.05, 0.1, 0.5, 1.0],
        "regressor__l1_ratio": [0.1, 0.3, 0.5, 0.7, 0.9]
    }

    cv = KFold(
        n_splits=5,
        shuffle=True,
        random_state=42
    )

    grid = GridSearchCV(
        estimator=model,
        param_grid=param_grid,
        scoring="neg_mean_absolute_error",
        cv=cv,
        n_jobs=-1,
        verbose=1
    )

    grid.fit(X_train, y_train)

    print("Mejores parámetros:")
    print(grid.best_params_)

    print("Mejor MAE CV:")
    print(-grid.best_score_)


    # ============================================================
    # 8. Evaluación en test
    # ============================================================

    best_model = grid.best_estimator_

    y_pred = best_model.predict(X_test)

    # Opcional: recortar predicciones al rango válido [0, 1]
    y_pred_clipped = np.clip(y_pred, 0, 1)

    mae = mean_absolute_error(y_test, y_pred_clipped)
    rmse = mean_squared_error(y_test, y_pred_clipped) ** 0.5
    r2 = r2_score(y_test, y_pred_clipped)

    print("\nMétricas en test:")
    print("MAE :", mae)
    print("RMSE:", rmse)
    print("R2  :", r2)

    print("\nInterpretación MAE:")
    print(f"Error promedio en escala 0-1: {mae:.4f}")
    print(f"Error promedio equivalente en escala 1-10: {mae * 10:.2f} puntos")


    # ============================================================
    # 9. Comparación predicción vs real
    # ============================================================

    results = X_test.copy()
    results["y_real"] = y_test
    results["y_pred"] = y_pred_clipped
    results["abs_error"] = np.abs(results["y_real"] - results["y_pred"])

    print("\nPeores predicciones:")
    print(
        results
        .sort_values("abs_error", ascending=False)
        .head(10)[["title", "y_real", "y_pred", "abs_error"]]
    )

    print("\nMejores predicciones:")
    print(
        results
        .sort_values("abs_error", ascending=True)
        .head(10)[["title", "y_real", "y_pred", "abs_error"]]
    )

def main() -> None:
    pipeline = Pipeline([("model", ConstantRatingModel(value=DUMMY_VALUE))])
    pipeline.fit([{}], [DUMMY_VALUE])

    version = publish(
        pipeline=pipeline,
        project=WANDB_PROJECT,
        artifact_name=WANDB_ARTIFACT,
        entity=WANDB_ENTITY,
        alias=WANDB_ALIAS,
        metadata={"strategy": "constant", "value": DUMMY_VALUE},
        run_name=f"dummy-constant-{DUMMY_VALUE}",
    )
    print(f"Published {WANDB_ARTIFACT} {version} with alias '{WANDB_ALIAS}'")


if __name__ == "__main__":
    #main()
    train_elastic_net()
