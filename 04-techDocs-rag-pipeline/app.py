"""
04-techDocs-rag-pipeline/app.py

Technical Documentation Assistant — Streamlit app.

Run:
    cd 04-techDocs-rag-pipeline
    streamlit run app.py

Features:
  - Hybrid search (Dense Milvus + BM25 + RRF + CrossEncoder rerank)
  - Live evaluation metrics panel (Faithfulness, Relevancy)
  - Retrieval method explainer
  - Batch evaluation mode with downloadable report
  - Upload additional documentation
"""

import sys
import os
import json
import tempfile
import logging
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import (
    DocumentIngestionPipeline,
    HybridQueryEngine,
    RAGEvaluator,
    DEFAULT_EVAL_QUESTIONS,
)
from shared.utils import ollama_warning, pretty_sources

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="TechDocs RAG Pipeline",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .metric-row {
    display: flex;
    gap: 1rem;
    margin: 0.5rem 0;
  }
  .metric-box {
    background: #1e2130;
    border-radius: 10px;
    padding: 1rem;
    text-align: center;
    flex: 1;
  }
  .metric-val { font-size: 2rem; font-weight: 700; }
  .metric-lbl { font-size: 0.75rem; color: #718096; text-transform: uppercase; }
  .pass  { color: #68d391; }
  .fail  { color: #fc8181; }
  .source-box {
    background: #1a1f2e;
    border-left: 3px solid #4299e1;
    padding: 0.6rem 1rem;
    margin: 0.3rem 0;
    border-radius: 0 6px 6px 0;
    font-size: 0.82rem;
  }
  .pipeline-badge {
    background: #2d3748;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.75rem;
    color: #a0aec0;
    display: inline-block;
    margin: 2px;
  }
</style>
""", unsafe_allow_html=True)


def init_session():
    if "ingest_pipeline" not in st.session_state:
        st.session_state.ingest_pipeline = DocumentIngestionPipeline()
    if "query_engine" not in st.session_state:
        st.session_state.query_engine = None
    if "evaluator" not in st.session_state:
        st.session_state.evaluator = None
    if "last_eval" not in st.session_state:
        st.session_state.last_eval = None
    if "use_reranker" not in st.session_state:
        st.session_state.use_reranker = True
    if "indexed" not in st.session_state:
        st.session_state.indexed = False


def build_engine():
    data_dir = str(Path(__file__).parent / "data")
    pipeline = st.session_state.ingest_pipeline
    with st.spinner("Building hybrid search index (Milvus + BM25)…"):
        index, nodes = pipeline.get_or_ingest(data_dir)
        st.session_state.query_engine = HybridQueryEngine(
            index=index,
            nodes=nodes,
            use_reranker=st.session_state.use_reranker,
        )
        st.session_state.evaluator = RAGEvaluator()
        st.session_state.indexed = True


def render_sidebar():
    with st.sidebar:
        st.title("⚡ TechDocs RAG")
        st.caption("Hybrid Search · Milvus · BM25 · CrossEncoder")

        warn = ollama_warning()
        if warn:
            st.warning(warn, icon="⚠️")

        st.divider()
        st.subheader("🔧 Retrieval Config")
        use_reranker = st.toggle(
            "Cross-encoder reranker",
            value=st.session_state.use_reranker,
            help="ms-marco-MiniLM-L-6-v2 — downloads ~85MB on first use",
        )
        if use_reranker != st.session_state.use_reranker:
            st.session_state.use_reranker = use_reranker
            st.session_state.query_engine = None  # force rebuild
            st.session_state.indexed = False

        st.markdown("""
        **Pipeline stages:**
        """)
        for stage in [
            "1️⃣ Dense — Milvus cosine (top-8)",
            "2️⃣ Sparse — BM25 keyword (top-8)",
            "3️⃣ Fusion — Reciprocal Rank (top-6)",
            "4️⃣ Rerank — CrossEncoder (top-3)" if use_reranker else "4️⃣ Reranker OFF",
            "5️⃣ Synthesize — Groq LLM",
        ]:
            st.markdown(f'<span class="pipeline-badge">{stage}</span>', unsafe_allow_html=True)

        st.divider()
        st.subheader("📄 Add Documentation")
        uploaded = st.file_uploader(
            "Upload tech docs (PDF/TXT/MD)",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
        )
        if uploaded and st.button("Index Files", type="primary"):
            pipeline = st.session_state.ingest_pipeline
            for f in uploaded:
                suffix = Path(f.name).suffix
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(f.read())
                tmp.close()
                tmpdir = tempfile.mkdtemp()
                os.rename(tmp.name, os.path.join(tmpdir, f.name))
                pipeline.ingest(tmpdir, overwrite=False)
                os.rmdir(tmpdir)
            st.session_state.query_engine = None
            st.session_state.indexed = False
            st.success("Re-indexing with new documents…")
            st.rerun()

        st.divider()
        if st.button("🔄 Re-index All Docs"):
            st.session_state.query_engine = None
            st.session_state.indexed = False
            data_dir = str(Path(__file__).parent / "data")
            pipeline = st.session_state.ingest_pipeline
            pipeline.ingest(data_dir, overwrite=True)
            st.rerun()


def render_query_tab():
    st.subheader("Ask your tech docs")
    st.caption("Hybrid retrieval: Milvus dense + BM25 sparse + RRF fusion + cross-encoder rerank")

    q = st.text_input(
        "Question",
        placeholder="E.g. 'How do I set up webhook events?' or 'What are the API rate limits?'",
    )

    example_qs = [
        "How do I authenticate with the API?",
        "What are the rate limits for API calls?",
        "How do I configure a webhook endpoint?",
        "What error code means invalid API key?",
        "How do I filter events by date range?",
    ]
    st.caption("Quick examples:")
    cols = st.columns(len(example_qs))
    for i, eq in enumerate(example_qs):
        with cols[i]:
            if st.button(eq, key=f"eq_{i}", use_container_width=True):
                q = eq

    if q and st.button("🔍 Search", type="primary", use_container_width=True):
        if not st.session_state.query_engine:
            st.error("Index not ready. Click 'Re-index All Docs' in the sidebar.")
            return

        with st.spinner("Retrieving and synthesising…"):
            result = st.session_state.query_engine.query(q)

        st.markdown(f"### Answer\n{result['answer']}")

        # Retrieval method badge
        st.markdown(
            f'<span class="pipeline-badge">🔍 {result["retrieval_method"]}</span>',
            unsafe_allow_html=True,
        )

        # Sources
        if result["sources"]:
            with st.expander(f"📎 {len(result['sources'])} source chunks", expanded=True):
                for s in result["sources"]:
                    st.markdown(
                        f'<div class="source-box"><strong>{s["file"]}</strong> '
                        f'(score: {s["score"]}) — p.{s["page"]}<br>'
                        f'<small>{s["excerpt"]}</small></div>',
                        unsafe_allow_html=True,
                    )

        # Live evaluation
        st.divider()
        st.subheader("📊 Real-time Evaluation")
        with st.spinner("Running LLM-as-judge evaluation…"):
            raw_response = st.session_state.query_engine.query_engine.query(q)
            eval_result = st.session_state.evaluator.evaluate_response(
                q, raw_response, result["retrieval_method"]
            )

        col1, col2, col3 = st.columns(3)
        faith_cls = "pass" if eval_result.faithfulness_pass else "fail"
        relev_cls = "pass" if eval_result.relevancy_pass else "fail"
        with col1:
            st.markdown(
                f'<div class="metric-box">'
                f'<div class="metric-val {faith_cls}">{eval_result.faithfulness_score:.2f}</div>'
                f'<div class="metric-lbl">Faithfulness</div></div>',
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                f'<div class="metric-box">'
                f'<div class="metric-val {relev_cls}">{eval_result.relevancy_score:.2f}</div>'
                f'<div class="metric-lbl">Relevancy</div></div>',
                unsafe_allow_html=True,
            )
        with col3:
            overall_cls = "pass" if eval_result.overall_pass else "fail"
            overall_val = "PASS" if eval_result.overall_pass else "FAIL"
            st.markdown(
                f'<div class="metric-box">'
                f'<div class="metric-val {overall_cls}">{overall_val}</div>'
                f'<div class="metric-lbl">Overall</div></div>',
                unsafe_allow_html=True,
            )

        if eval_result.feedback:
            with st.expander("Evaluator feedback"):
                st.info(eval_result.feedback)


def render_eval_tab():
    st.subheader("Batch Evaluation")
    st.caption(
        "Run the full evaluation suite across multiple questions. "
        "Results include per-question faithfulness and relevancy scores."
    )

    st.markdown("**Test questions:**")
    for q in DEFAULT_EVAL_QUESTIONS:
        st.markdown(f"- {q}")

    if st.button("▶️ Run Batch Evaluation", type="primary"):
        if not st.session_state.query_engine:
            st.error("Index not ready.")
            return

        progress = st.progress(0, "Evaluating…")
        results_placeholder = st.empty()

        with st.spinner("Running evaluation suite…"):
            eval_summary = st.session_state.evaluator.batch_evaluate(
                questions=DEFAULT_EVAL_QUESTIONS,
                query_engine=st.session_state.query_engine,
            )
            st.session_state.last_eval = eval_summary

        progress.progress(100, "Done!")

        summary = eval_summary.get("summary", {})
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Questions", summary.get("questions_evaluated"))
        col2.metric("Avg Faithfulness", f"{summary.get('avg_faithfulness', 0):.2f}")
        col3.metric("Avg Relevancy", f"{summary.get('avg_relevancy', 0):.2f}")
        col4.metric("Pass Rate", f"{summary.get('overall_pass_rate', 0):.0%}")

        st.divider()
        for r in eval_summary.get("results", []):
            faith_icon = "✅" if r["faithfulness_pass"] else "❌"
            relev_icon = "✅" if r["relevancy_pass"] else "❌"
            with st.expander(f"{faith_icon}{relev_icon} {r['question'][:80]}"):
                st.write(f"**Answer:** {r['answer'][:300]}…")
                st.write(
                    f"Faithfulness: **{r['faithfulness_score']}** | "
                    f"Relevancy: **{r['relevancy_score']}** | "
                    f"Sources: {r['sources_used']}"
                )

        st.download_button(
            "⬇️ Download evaluation report (JSON)",
            data=json.dumps(eval_summary, indent=2),
            file_name="rag_eval_report.json",
            mime="application/json",
        )


def main():
    init_session()
    render_sidebar()

    st.title("⚡ Technical Documentation Assistant")
    st.caption("End-to-end RAG: Milvus · BM25 · RRF Fusion · CrossEncoder · Eval")

    if not st.session_state.indexed:
        st.info("Building the hybrid search index on first run. This takes ~30 seconds.")
        build_engine()
        st.rerun()

    tab_query, tab_eval = st.tabs(["🔍 Query", "📊 Evaluate"])

    with tab_query:
        render_query_tab()

    with tab_eval:
        render_eval_tab()


if __name__ == "__main__":
    main()
