# Training

Publishes the current model to the W&B Artifact registry with the alias
`production`. The serving API (`deployment/`) loads whatever artifact carries
that alias.

## Run locally

```bash
pip install -e ./src
wandb login                          # paste your personal W&B API key

export WANDB_ENTITY=mlprod-obli      # team in W&B
export WANDB_PROJECT=imdb-rating

python training/train.py
```

Expected tail of the output:

```
Published imdb-rating-model v0 with alias 'production'
```

After running, the artifact is visible at:
`https://wandb.ai/mlprod-obli/imdb-rating/artifacts/model/imdb-rating-model/production`

## Current state

The model is a constant predictor (`ConstantRatingModel(value=8)`) - the goal
of this first iteration is to validate the training -> registry -> serving
loop, not the model quality. A real featurizer + classifier replaces this in a
follow-up PR.

## Environment variables

| Variable          | Default              | Purpose                              |
| ----------------- | -------------------- | ------------------------------------ |
| `WANDB_ENTITY`    | `mlprod-obli`        | W&B team owning the project          |
| `WANDB_PROJECT`   | `imdb-rating`        | W&B project name                     |
| `WANDB_ARTIFACT`  | `imdb-rating-model`  | Artifact name in the registry        |
| `WANDB_ALIAS`     | `production`         | Alias attached to the new version    |
| `DUMMY_VALUE`     | `8`                  | Constant value the dummy predicts    |
