"""
03-marketing-content-hub/app.py

Product Marketing Content Hub — Streamlit application.

Run:
    cd 03-marketing-content-hub
    streamlit run app.py

Features:
  - Auto-indexes product knowledge base on first run
  - Upload additional documents to any knowledge collection
  - Select content type (LinkedIn, Blog, Demo Script, Email, Case Study)
  - Stream AI-generated content grounded in product knowledge
  - Copy to clipboard / download generated content
  - Collection health dashboard
"""

import sys
import os
import tempfile
import logging
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import (
    KnowledgeIngestionPipeline,
    ContentGenerationEngine,
    ContentType,
    TEMPLATES,
    COLLECTIONS,
)
from shared.utils import ollama_warning

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Marketing Content Hub",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .content-output {
    background: #1a1f2e;
    border: 1px solid #2d3250;
    border-radius: 10px;
    padding: 1.5rem;
    font-family: sans-serif;
    line-height: 1.7;
    white-space: pre-wrap;
  }
  .collection-card {
    background: #1e2130;
    border-left: 3px solid #6C63FF;
    padding: 0.7rem 1rem;
    border-radius: 0 8px 8px 0;
    margin: 0.4rem 0;
  }
  .tag {
    display: inline-block;
    background: #2d3250;
    color: #a0aec0;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    margin: 2px;
  }
</style>
""", unsafe_allow_html=True)

CONTENT_TYPE_LABELS = {
    ContentType.LINKEDIN_POST:      "💼 LinkedIn Post",
    ContentType.BLOG_ARTICLE:       "📝 Blog Article",
    ContentType.DEMO_SCRIPT:        "🎬 Demo Script",
    ContentType.EMAIL_CAMPAIGN:     "📧 Email Campaign (3-touch)",
    ContentType.CASE_STUDY_SNIPPET: "📊 Case Study Snippet",
}

TOPIC_SUGGESTIONS = {
    ContentType.LINKEDIN_POST: [
        "How FashionHub cut $9.7M in excess inventory with AI",
        "Why real-time analytics beats dashboards from yesterday",
        "The hidden cost of manual churn detection in B2B SaaS",
    ],
    ContentType.BLOG_ARTICLE: [
        "5 Signs Your Business Is Flying Blind With Lagging Indicators",
        "How Predictive Analytics Reduces SaaS Churn by 34%",
        "The Real-Time Revolution: Why Batch Analytics Is Obsolete",
    ],
    ContentType.DEMO_SCRIPT: [
        "15-minute demo for a retail VP of Supply Chain",
        "Discovery-led demo for a B2B SaaS VP Customer Success",
        "Technical demo for logistics operations director",
    ],
    ContentType.EMAIL_CAMPAIGN: [
        "3-email sequence for VP of Operations at mid-market retailers",
        "Nurture sequence for heads of customer success in SaaS",
    ],
    ContentType.CASE_STUDY_SNIPPET: [
        "FashionHub inventory optimisation results",
        "CloudServe churn reduction with DataFlow AI",
        "QuickFreight on-time delivery improvement",
    ],
}


def init_session():
    if "pipeline" not in st.session_state:
        with st.spinner("Initialising knowledge base…"):
            pipeline = KnowledgeIngestionPipeline()
            data_dir = Path(__file__).parent / "data"
            if data_dir.exists():
                pipeline.ingest_directory(str(data_dir), "product_features")
                pipeline.ingest_directory(str(data_dir), "case_studies")
                pipeline.ingest_directory(str(data_dir), "faqs")
            st.session_state.pipeline = pipeline
            st.session_state.engine = ContentGenerationEngine(pipeline)
    if "history" not in st.session_state:
        st.session_state.history = []


def render_sidebar():
    with st.sidebar:
        st.title("🚀 Content Hub")
        st.caption("DataFlow AI • Marketing Intelligence")

        warn = ollama_warning()
        if warn:
            st.warning(warn, icon="⚠️")

        st.divider()
        st.subheader("📚 Knowledge Collections")
        stats = st.session_state.pipeline.collection_stats()
        for name, info in stats.items():
            vectors = info.get("vectors", 0)
            desc = info.get("description", "")
            st.markdown(
                f'<div class="collection-card">'
                f'<strong>{name}</strong>'
                f'<span class="tag">{vectors} chunks</span>'
                f'<br><small style="color:#718096">{desc}</small>'
                f'</div>',
                unsafe_allow_html=True,
            )

        st.divider()
        st.subheader("➕ Add Knowledge")
        col_choice = st.selectbox(
            "Target collection",
            options=list(COLLECTIONS.keys()),
            format_func=lambda x: x.replace("_", " ").title(),
        )
        uploaded = st.file_uploader(
            "Upload PDF or text file",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
        )
        if uploaded and st.button("Index Documents", type="primary"):
            for f in uploaded:
                suffix = Path(f.name).suffix
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(f.read())
                tmp.close()
                n = st.session_state.pipeline.ingest_file(tmp.name, col_choice)
                os.unlink(tmp.name)
            st.success(f"✅ Indexed into '{col_choice}'")
            st.rerun()

        if st.session_state.history:
            st.divider()
            st.subheader(f"📋 History ({len(st.session_state.history)})")
            for i, item in enumerate(reversed(st.session_state.history[-5:])):
                st.caption(f"**{item['type']}** — {item['topic'][:40]}…")


def main():
    init_session()
    render_sidebar()

    st.title("🚀 Product Marketing Content Hub")
    st.caption("Generate grounded, on-brand content from your product knowledge base")

    st.divider()
    col_type, col_config = st.columns([1, 2])

    with col_type:
        st.subheader("Content Type")
        content_type = st.radio(
            "Select output format",
            options=list(ContentType),
            format_func=lambda ct: CONTENT_TYPE_LABELS[ct],
            label_visibility="collapsed",
        )
        tmpl = TEMPLATES[content_type]
        st.markdown(f"""
        <div class="collection-card">
        <strong>{tmpl.name}</strong><br>
        <small>{tmpl.description}</small><br>
        <span class="tag">📏 {tmpl.expected_length}</span>
        <span class="tag">🎭 {tmpl.tone[:25]}</span>
        </div>
        """, unsafe_allow_html=True)

    with col_config:
        st.subheader("Topic & Angle")
        suggestions = TOPIC_SUGGESTIONS.get(content_type, [])
        if suggestions:
            st.caption("💡 Quick suggestions:")
            chosen = st.selectbox(
                "Pick a suggestion or write your own",
                ["— write my own topic —"] + suggestions,
                label_visibility="collapsed",
            )
        else:
            chosen = "— write my own topic —"

        if chosen == "— write my own topic —":
            topic = st.text_area(
                "What should this content be about?",
                height=100,
                placeholder="E.g. 'How real-time analytics helped a retailer reduce overstock by 23%'",
            )
        else:
            topic = chosen
            st.info(f"📌 Topic: {topic}")

        generate_btn = st.button(
            f"✨ Generate {CONTENT_TYPE_LABELS[content_type]}",
            disabled=not topic.strip(),
            type="primary",
            use_container_width=True,
        )

    st.divider()

    if generate_btn and topic.strip():
        st.subheader(f"Generated {TEMPLATES[content_type].name}")

        with st.container():
            output_placeholder = st.empty()
            full_output = ""

            with st.spinner("Retrieving context and generating…"):
                for token in st.session_state.engine.generate_stream(
                    topic, content_type
                ):
                    full_output += token
                    output_placeholder.markdown(
                        f'<div class="content-output">{full_output}▌</div>',
                        unsafe_allow_html=True,
                    )

            output_placeholder.markdown(
                f'<div class="content-output">{full_output}</div>',
                unsafe_allow_html=True,
            )

        col_dl, col_copy = st.columns([1, 1])
        with col_dl:
            st.download_button(
                "⬇️ Download as .txt",
                data=full_output,
                file_name=f"{content_type.value}_{topic[:30].replace(' ','_')}.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_copy:
            st.code(full_output[:200] + "…", language=None)

        st.session_state.history.append({
            "type": TEMPLATES[content_type].name,
            "topic": topic,
            "output": full_output,
        })


if __name__ == "__main__":
    main()
