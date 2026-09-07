"""
02-contract-review-chat/app.py

Contract Review Assistant — Streamlit web application.

Run:
    cd 02-contract-review-chat
    streamlit run app.py

Features:
  - Drag-and-drop PDF/text upload (multiple files)
  - Full streaming chat interface
  - Per-session chat history
  - Source attribution per response
  - One-click conversation reset
  - Suggested starter questions
"""

import sys
import os
import tempfile
import logging
from pathlib import Path
from typing import List

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.utils import ollama_warning
from rag_engine import ContractReviewEngine

logger = logging.getLogger(__name__)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Contract Review Assistant",
    page_icon="📜",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stChatMessage { border-radius: 10px; }
  .source-card {
    background: #1e2130;
    border-left: 3px solid #6C63FF;
    padding: 0.6rem 1rem;
    margin: 0.3rem 0;
    border-radius: 0 6px 6px 0;
    font-size: 0.82rem;
  }
  .metric-badge {
    display: inline-block;
    background: #2d3250;
    color: #a0aec0;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    margin: 2px;
  }
  .risk-high   { border-left-color: #fc8181 !important; }
  .risk-medium { border-left-color: #f6ad55 !important; }
  .risk-low    { border-left-color: #68d391 !important; }
</style>
""", unsafe_allow_html=True)

STARTER_QUESTIONS = [
    "Summarise the key obligations of each party",
    "What are the payment terms and late payment consequences?",
    "What is the contract duration and renewal mechanism?",
    "Identify any liability caps or indemnification clauses",
    "What are the grounds and process for termination?",
    "What SLA commitments are defined and what are the remedies?",
    "Who owns intellectual property created under this contract?",
    "What confidentiality obligations exist and for how long?",
    "Flag any unusual or potentially risky clauses",
    "What is the dispute resolution process?",
]


def init_session() -> None:
    """Initialise session state with sensible defaults."""
    if "engine" not in st.session_state:
        st.session_state.engine = ContractReviewEngine()
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "indexed_files" not in st.session_state:
        st.session_state.indexed_files = []
    if "show_sources" not in st.session_state:
        st.session_state.show_sources = True


def render_sidebar() -> List[str]:
    """Render the sidebar and return list of temp file paths to index."""
    with st.sidebar:
        st.title("📜 Contract Review")
        st.caption("Powered by Groq + Ollama")

        # Ollama health check
        warn = ollama_warning()
        if warn:
            st.warning(warn, icon="⚠️")

        st.divider()
        st.subheader("📂 Upload Contracts")
        uploaded = st.file_uploader(
            "Drop PDF or text files here",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
            help="Upload one or more contract documents to analyse",
        )

        temp_paths = []
        if uploaded:
            for f in uploaded:
                suffix = Path(f.name).suffix
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, suffix=suffix, prefix="contract_"
                )
                tmp.write(f.read())
                tmp.close()
                temp_paths.append(tmp.name)

        st.divider()
        st.subheader("⚙️ Settings")
        st.session_state.show_sources = st.toggle(
            "Show source excerpts", value=st.session_state.show_sources
        )

        if st.session_state.indexed_files:
            st.divider()
            st.subheader("📋 Loaded Documents")
            for fname in st.session_state.indexed_files:
                st.markdown(f"✅ `{fname}`")

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.engine.reset_memory()
                st.rerun()
        with col2:
            if st.button("🔄 Reset All", use_container_width=True):
                st.session_state.engine.clear()
                st.session_state.messages = []
                st.session_state.indexed_files = []
                st.rerun()

        st.divider()
        st.caption("💡 **Tips**")
        st.caption("• Ask follow-up questions — the bot remembers context")
        st.caption("• Try: 'What risk does clause 8 pose?'")
        st.caption("• Try: 'Compare the indemnity clauses across both contracts'")

    return temp_paths


def render_chat() -> None:
    """Render the main chat interface."""
    st.title("Contract Review Assistant")
    st.caption("AI-powered contract intelligence — ask anything about your contracts")

    engine: ContractReviewEngine = st.session_state.engine

    # ── Starter questions ─────────────────────────────────────────────────────
    if not st.session_state.messages and engine.is_ready:
        st.markdown("#### 💡 Suggested questions")
        cols = st.columns(2)
        for i, q in enumerate(STARTER_QUESTIONS[:6]):
            with cols[i % 2]:
                if st.button(q, key=f"sq_{i}", use_container_width=True):
                    st.session_state.messages.append({"role": "user", "content": q})
                    st.rerun()

    # ── Chat history ──────────────────────────────────────────────────────────
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources") and st.session_state.show_sources:
                with st.expander(f"📎 {len(msg['sources'])} source(s) used", expanded=False):
                    for s in msg["sources"]:
                        st.markdown(
                            f'<div class="source-card">'
                            f'<strong>{s["file"]}</strong>'
                            f'<span class="metric-badge">p.{s["page"]}</span>'
                            f'<span class="metric-badge">score: {s["score"]}</span>'
                            f'<br><small>{s["excerpt"]}</small>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

    # ── Chat input ────────────────────────────────────────────────────────────
    if prompt := st.chat_input(
        "Ask about your contract…",
        disabled=not engine.is_ready,
    ):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            full_response = st.write_stream(engine.chat_stream(prompt))

        # Store message with source attribution
        st.session_state.messages.append({
            "role": "assistant",
            "content": full_response,
            "sources": engine.get_sources(prompt) if st.session_state.show_sources else [],
        })
        st.rerun()


def main() -> None:
    init_session()
    temp_paths = render_sidebar()

    # ── Index new uploads ─────────────────────────────────────────────────────
    if temp_paths:
        engine: ContractReviewEngine = st.session_state.engine
        new_files = [p for p in temp_paths if Path(p).name not in st.session_state.indexed_files]
        if new_files:
            with st.spinner(f"Indexing {len(new_files)} document(s)…"):
                n_chunks = engine.load_documents(new_files)
                st.session_state.indexed_files.extend(engine.loaded_files)
            st.success(
                f"✅ Indexed {len(new_files)} document(s) into {n_chunks} chunks. "
                "Start chatting below!"
            )
            # Clean up temp files
            for p in temp_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # ── No documents loaded — show landing ────────────────────────────────────
    if not st.session_state.engine.is_ready:
        st.markdown("""
        ## 📜 Welcome to the Contract Review Assistant

        Upload one or more contracts in the **sidebar** to get started.

        **What you can do:**
        - 🔍 Ask plain-English questions about contract terms
        - ⚠️ Identify risks, obligations, and deadlines
        - 💬 Ask follow-up questions with full conversation memory
        - 📑 Review multiple contracts simultaneously
        - 🔗 Get cited excerpts for every answer

        **Supported formats:** PDF, TXT, Markdown
        """)
    else:
        render_chat()


if __name__ == "__main__":
    main()
