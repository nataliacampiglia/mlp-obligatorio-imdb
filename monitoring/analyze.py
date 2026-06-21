"""Streamlit monitoring dashboard.

Reads prediction events from the public S3 bucket and renders panels for
volume, error, drift and model comparison. Designed to be run as its own
service alongside the FastAPI inference server.

Run:
    streamlit run monitoring/analyze.py
"""
import io
import json
import os
from datetime import datetime, timezone

import boto3
import pandas as pd
import plotly.express as px
import streamlit as st
from botocore import UNSIGNED
from botocore.config import Config

BUCKET_NAME = os.getenv("OBS_BUCKET_NAME", "mlp-imdb-observability-2026")
BUCKET_REGION = os.getenv("OBS_BUCKET_REGION", "us-east-1")
PREFIX = "predictions/"

st.set_page_config(page_title="MovieRate Monitoring", layout="wide")
st.title("MovieRate AI — Monitoring")
st.caption(f"Bucket: `{BUCKET_NAME}` (public).")


@st.cache_data(ttl=10)
def load_records() -> pd.DataFrame:
    s3 = boto3.client(
        "s3",
        config=Config(signature_version=UNSIGNED),
        region_name=BUCKET_REGION,
    )
    records = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET_NAME, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=BUCKET_NAME, Key=obj["Key"])["Body"].read()
            try:
                records.append(json.loads(body))
            except Exception:
                pass
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    return df.sort_values("ts")


df = load_records()

col_refresh, col_count = st.columns([1, 4])
with col_refresh:
    if st.button("Refresh", use_container_width=True):
        load_records.clear()
        st.rerun()
with col_count:
    st.caption(f"Loaded {len(df)} prediction events (auto-refresh every 10s).")

if df.empty:
    st.info("No predictions logged yet. Make a prediction at http://localhost:8000.")
    st.stop()

with_truth = df.dropna(subset=["real_rating"])
mae = with_truth["error"].mean() if not with_truth.empty else None
acc1 = (with_truth["error"] < 1).mean() if not with_truth.empty else None
versions_active = df["model_version"].nunique()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total predictions", len(df))
c2.metric("MAE (vs IMDb real)", f"{mae:.2f}" if mae is not None else "—")
c3.metric("Accuracy ±1 point", f"{acc1 * 100:.1f}%" if acc1 is not None else "—")
c4.metric("Model versions seen", versions_active)

st.divider()

st.subheader("Prediction vs Real (IMDb)")
if not with_truth.empty:
    scatter = px.scatter(
        with_truth,
        x="real_rating",
        y="prediction",
        color="error",
        hover_data=["movie_title", "model_version", "model_strategy"],
        color_continuous_scale="RdYlGn_r",
        range_x=[1, 10],
        range_y=[1, 10],
    )
    scatter.add_shape(type="line", x0=1, y0=1, x1=10, y1=10, line=dict(dash="dash"))
    st.plotly_chart(scatter, use_container_width=True)
else:
    st.info("No predictions with ground truth yet (OMDb did not return imdbRating).")

st.subheader("Error distribution")
left, right = st.columns(2)
with left:
    if not with_truth.empty:
        hist = px.histogram(with_truth, x="error", nbins=20, title="Absolute error (pts)")
        st.plotly_chart(hist, use_container_width=True)
with right:
    if not with_truth.empty:
        window = st.selectbox(
            "Time range",
            options=["1H", "1D", "7D", "All"],
            index=1,
            key="rolling_window",
        )
        ranges = {
            "1H":  (pd.Timedelta(hours=1),  "5min"),
            "1D":  (pd.Timedelta(days=1),   "30min"),
            "7D":  (pd.Timedelta(days=7),   "6h"),
        }
        now = pd.Timestamp.now(tz="UTC")
        if window in ranges:
            cutoff, roll = ranges[window]
            df_w = with_truth[with_truth["ts"] >= now - cutoff]
        else:
            df_w = with_truth
            roll = "1D"

        if df_w.empty:
            st.info(f"No predictions in the last {window}.")
        else:
            series = df_w.set_index("ts")["error"].sort_index()
            rolling = series.rolling(roll).mean().reset_index()
            line = px.line(rolling, x="ts", y="error", title=f"Rolling MAE ({roll} window, last {window})")
            line.update_xaxes(range=[now - cutoff if window in ranges else df_w["ts"].min(), now])
            st.plotly_chart(line, use_container_width=True)

st.subheader("Model comparison")
if not with_truth.empty:
    by_version = with_truth.groupby("model_version", as_index=False)["error"].mean()
    bar = px.bar(by_version, x="model_version", y="error", title="MAE per model_version")
    st.plotly_chart(bar, use_container_width=True)

st.subheader("Recent predictions")
recent_cols = ["ts", "movie_title", "prediction", "real_rating", "error", "model_version", "model_strategy"]
recent = df.sort_values("ts", ascending=False).head(20)[recent_cols]
st.dataframe(recent, use_container_width=True, hide_index=True)
