import time
import random
import uuid
from datetime import datetime, timezone

import httpx
import pandas as pd
import streamlit as st

import os

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Content Moderation Demo",
    layout="wide",
    page_icon="🛡️",
)

if "history" not in st.session_state:
    st.session_state.history = []

if "metrics_log" not in st.session_state:
    # List of dicts: {timestamp, label, confidence, inference_time_ms, cached}
    st.session_state.metrics_log = []

if "batch_job_id" not in st.session_state:
    st.session_state.batch_job_id = None

if "batch_df" not in st.session_state:
    st.session_state.batch_df = None


# ---------------------------------------------------------------------------
# Helper: test data generator
# ---------------------------------------------------------------------------
def generate_test_data(n=100):
    toxic_templates = [
        "I hate {group}",
        "Kill all {group}",
        "{group} should die",
        "{group} are disgusting",
        "Destroy all {group}",
    ]
    clean_templates = [
        "Great day!",
        "Love this product",
        "Thanks so much",
        "Amazing experience",
        "Well done team",
        "Looking forward to it",
        "Best service ever",
    ]
    groups = ["everyone", "users", "people", "them"]

    toxic = [
        random.choice(toxic_templates).format(group=random.choice(groups))
        for _ in range(int(n * 0.3))
    ]
    clean = [random.choice(clean_templates) for _ in range(int(n * 0.7))]
    comments = toxic + clean
    random.shuffle(comments)
    return pd.DataFrame({"comment": comments})


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("🛡️ Settings")
default_api_url = os.environ.get("API_URL", "http://localhost:8000")
api_url = st.sidebar.text_input("API URL", value=default_api_url)

# Quick health check
health_status = "unknown"
health_color = "🔴"
try:
    r = httpx.get(f"{api_url}/health", timeout=5)
    if r.status_code == 200:
        h = r.json()
        if h.get("status") == "healthy":
            health_status = "healthy"
            health_color = "🟢"
        elif h.get("status") == "degraded":
            health_status = "degraded"
            health_color = "🟡"
        else:
            health_status = "unhealthy"
            health_color = "🔴"
except Exception:
    pass

st.sidebar.markdown(f"**Health:** {health_color} {health_status}")

# Queue depth (if available)
try:
    r = httpx.get(f"{api_url}/health", timeout=2)
    if r.status_code == 200:
        # We don't have a dedicated /metrics endpoint, but health may expose queue info later.
        # For now we just keep a simple placeholder.
        st.sidebar.markdown("*Queue depth shown in Batch Processing tab*")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_single, tab_batch, tab_metrics = st.tabs(
    ["Single Comment", "Batch Processing", "System Metrics"]
)

# ==========================================================================
# TAB 1 — Single Comment
# ==========================================================================
with tab_single:
    st.header("Single Comment Moderation")
    comment_text = st.text_area("Enter a comment to moderate", height=120)
    submit = st.button("Moderate", type="primary")

    if submit and comment_text:
        start = time.time()
        try:
            resp = httpx.post(
                f"{api_url}/moderate",
                json={"comment": comment_text},
                timeout=30,
            )
            latency = (time.time() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                result = data["result"]

                # Store in session history
                st.session_state.history.insert(
                    0,
                    {
                        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                        "comment": comment_text[:80],
                        "label": result["label"],
                        "confidence": result["confidence"],
                        "cached": result.get("cached", False),
                        "hash": result.get("comment_hash", "")[:8],
                        "latency_ms": round(latency, 2),
                    },
                )
                st.session_state.history = st.session_state.history[:10]

                # Metrics log
                st.session_state.metrics_log.append(
                    {
                        "timestamp": datetime.now(),
                        "label": result["label"],
                        "confidence": result["confidence"],
                        "inference_time_ms": result.get("inference_time_ms", 0),
                        "cached": result.get("cached", False),
                    }
                )

                # Result display
                col1, col2 = st.columns([1, 2])
                with col1:
                    if result["label"] == "toxic":
                        st.error("🔴 TOXIC")
                    else:
                        st.success("🟢 SAFE")

                    st.metric("Confidence", f"{result['confidence']:.2%}")
                    st.metric(
                        "Inference Time", f"{result.get('inference_time_ms', 0):.1f} ms"
                    )
                    if result.get("cached"):
                        st.markdown("⚡ **Cached**")
                    st.caption(f"Hash: `{result.get('comment_hash', '')[:8]}`")

                with col2:
                    scores = result.get("scores", {})
                    if scores:
                        st.bar_chart(
                            pd.Series(scores).sort_values(ascending=False),
                            use_container_width=True,
                        )

                st.markdown(f"**Request ID:** `{data.get('request_id', 'N/A')}`")
            else:
                st.error(f"API error {resp.status_code}: {resp.text}")
        except Exception as e:
            st.error(f"Request failed: {e}")

    # History table
    if st.session_state.history:
        st.divider()
        st.subheader("Recent Moderations (last 10)")
        st.dataframe(pd.DataFrame(st.session_state.history), use_container_width=True)

# ==========================================================================
# TAB 2 — Batch Processing
# ==========================================================================
with tab_batch:
    st.header("Batch Comment Processing")
    st.markdown("Upload a CSV or generate test data, then submit to the batch queue.")

    data_source = st.radio("Data source", ["Upload CSV", "Generate test data"])

    # ---- CSV Upload path ----
    if data_source == "Upload CSV":
        uploaded = st.file_uploader(
            "Upload CSV (must have a 'comment' column)", type=["csv"]
        )
        if uploaded:
            df = pd.read_csv(uploaded)
            if "comment" not in df.columns:
                st.error("CSV must contain a 'comment' column.")
                st.session_state.batch_df = None
            else:
                st.session_state.batch_df = df
                st.success(f"Loaded {len(df)} comments from CSV.")
        else:
            # Clear state if they switch away from a loaded CSV
            st.session_state.batch_df = None

    # ---- Generate path ----
    else:
        if st.button("Generate 100 fake comments"):
            st.session_state.batch_df = generate_test_data(100)
            st.success(
                f"Generated {len(st.session_state.batch_df)} comments (30% toxic, 70% clean)."
            )

    # ---- Unified display + submit (reads from session_state) ----
    df = st.session_state.batch_df

    if df is not None and not df.empty:
        st.write(f"Preview ({len(df)} comments):")
        st.dataframe(df.head(10), use_container_width=True)

        if st.button("Submit Batch", type="primary"):
            comments_payload = [{"comment": str(c)} for c in df["comment"].tolist()]
            try:
                resp = httpx.post(
                    f"{api_url}/moderate/batch",
                    json={"comments": comments_payload},
                    timeout=30,
                )
                if resp.status_code == 200:
                    batch_resp = resp.json()
                    st.session_state.batch_job_id = batch_resp["job_id"]
                    st.success("Batch queued successfully!")
                    st.json(batch_resp)
                else:
                    st.error(f"API error {resp.status_code}: {resp.text}")
            except Exception as e:
                st.error(f"Request failed: {e}")

    # ---- Active job monitor ----
    if st.session_state.batch_job_id:
        st.divider()
        st.subheader("Active Batch Job")
        st.write(f"**Job ID:** `{st.session_state.batch_job_id}`")

        try:
            health_r = httpx.get(f"{api_url}/health", timeout=2)
            if health_r.status_code == 200 and st.session_state.batch_df is not None:
                st.info(
                    f"Queued {len(st.session_state.batch_df)} comments. "
                    "Workers are processing via Service Bus queue."
                )
        except Exception:
            pass
# ==========================================================================
# TAB 3 — System Metrics
# ==========================================================================
with tab_metrics:
    st.header("System Metrics")

    col_a, col_b, col_c, col_d = st.columns(4)
    total_reqs = len(st.session_state.metrics_log)
    cached_reqs = sum(1 for m in st.session_state.metrics_log if m["cached"])
    hit_rate = (cached_reqs / total_reqs * 100) if total_reqs > 0 else 0
    avg_latency = (
        sum(m["inference_time_ms"] for m in st.session_state.metrics_log) / total_reqs
        if total_reqs > 0
        else 0
    )
    error_count = 0  # Not tracked in this simplified view

    col_a.metric("Total Requests", total_reqs)
    col_b.metric("Cache Hit Rate", f"{hit_rate:.1f}%")
    col_c.metric("Avg Latency", f"{avg_latency:.1f} ms")
    col_d.metric("Error Rate", "0%")

    if st.session_state.metrics_log:
        chart_df = pd.DataFrame(st.session_state.metrics_log)
        chart_df.set_index("timestamp", inplace=True)
        st.subheader("Requests Over Time")
        st.line_chart(chart_df.resample("1min").size(), use_container_width=True)
    else:
        st.caption("No data yet. Submit comments in the Single Comment tab.")

    st.divider()
    st.subheader("Architecture")
    st.image("architecture.png", width=800)
