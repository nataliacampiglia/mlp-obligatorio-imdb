"""Upload data to S3 as Parquet files."""

from __future__ import annotations

import io

import boto3
import pyarrow as pa
import pyarrow.parquet as pq


def upload_parquet(records: list[dict], bucket: str, key: str) -> None:
    table = pa.Table.from_pylist(records)
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    boto3.client("s3").upload_fileobj(buf, bucket, key)
