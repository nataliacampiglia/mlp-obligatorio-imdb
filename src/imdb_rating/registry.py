import os
import tempfile
from typing import Optional

import joblib
import wandb

ARTIFACT_FILENAME = "pipeline.joblib"


def get_production_metadata(
    project: str,
    artifact_name: str,
    entity: Optional[str] = None,
    alias: str = "production",
    api_key: Optional[str] = None,
) -> Optional[dict]:
    """Return the metadata dict of the current production artifact, or None if it doesn't exist."""
    try:
        api = wandb.Api(api_key=api_key) if api_key else wandb.Api()
        qualified = f"{entity}/{project}/{artifact_name}:{alias}" if entity else f"{project}/{artifact_name}:{alias}"
        artifact = api.artifact(qualified)
        return artifact.metadata
    except Exception:
        return None


def publish(
    pipeline,
    project: str,
    artifact_name: str,
    entity: Optional[str] = None,
    aliases: Optional[list] = None,
    metadata: Optional[dict] = None,
    run_name: Optional[str] = None,
) -> str:
    """Serialize a sklearn Pipeline and upload it to W&B as an Artifact.

    Returns the artifact version (e.g. "v0").
    """
    if aliases is None:
        aliases = ["production", "latest"]

    run = wandb.init(
        project=project,
        entity=entity,
        job_type="train",
        name=run_name,
        config=metadata or {},
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ARTIFACT_FILENAME)
            joblib.dump(pipeline, path)

            artifact = wandb.Artifact(
                artifact_name,
                type="model",
                metadata=metadata or {},
            )
            artifact.add_file(path)
            logged = run.log_artifact(artifact, aliases=aliases)
            logged.wait()
            version = logged.version
    finally:
        run.finish()
    return version


def load(
    project: str,
    artifact_name: str,
    entity: Optional[str] = None,
    alias: str = "production",
    api_key: Optional[str] = None,
):
    """Download the W&B artifact and deserialize the pipeline.

    Returns (pipeline, version).
    """
    api = wandb.Api(api_key=api_key) if api_key else wandb.Api()
    qualified = f"{entity}/{project}/{artifact_name}:{alias}" if entity else f"{project}/{artifact_name}:{alias}"
    artifact = api.artifact(qualified)
    download_dir = artifact.download()
    pipeline = joblib.load(os.path.join(download_dir, ARTIFACT_FILENAME))
    return pipeline, artifact.version
