"""Publish a dummy (constant) rating model to the W&B registry.

This is the first iteration of the training pipeline. The model itself is
trivial - it always predicts the same rating - and its only purpose is to
exercise the full training -> registry -> serving loop end-to-end. Real
featurization and learning come in a follow-up PR.
"""
from sklearn.pipeline import Pipeline

from imdb_rating.model import ConstantRatingModel
from imdb_rating.registry import publish

WANDB_ENTITY = "mlprod-obli"
WANDB_PROJECT = "imdb-rating"
WANDB_ARTIFACT = "imdb-rating-model"
WANDB_ALIAS = "production"
DUMMY_VALUE = 8


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
    main()
