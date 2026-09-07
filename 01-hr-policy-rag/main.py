"""
01-hr-policy-rag/main.py

HR Policy Q&A Bot — command-line interface.

Run:
    cd 01-hr-policy-rag
    python main.py
    python main.py --question "How many days of annual leave do I get?"
    python main.py --data-dir path/to/your/policies
"""

import argparse
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.utils import add_project_root, ollama_warning, pretty_sources
add_project_root(__file__)

from rag_pipeline import HRPolicyRAG

logger = logging.getLogger(__name__)

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║          Acme Corp — HR Policy Q&A Bot (RAG)                ║
║    Powered by: Groq (LLM) + Ollama nomic-embed-text         ║
╚══════════════════════════════════════════════════════════════╝
Type your question and press Enter. Type 'quit' or 'exit' to stop.
Type 'help' to see example questions.
"""

EXAMPLE_QUESTIONS = [
    "How many days of annual leave am I entitled to per year?",
    "Can I carry over unused leave to next year? How many days?",
    "What is the remote work policy? How many days per week?",
    "What are the core working hours?",
    "How do I submit an expense claim and what's the deadline?",
    "What is the parental leave entitlement for primary caregivers?",
    "What happens if I'm put on a performance improvement plan?",
    "Can I be reimbursed for alcohol on a client dinner?",
    "What constitutes a zero-tolerance policy violation?",
    "How much notice do I need to give before taking annual leave?",
]


def run_interactive(rag: HRPolicyRAG) -> None:
    print(BANNER)

    # Ollama connectivity warning
    warn = ollama_warning()
    if warn:
        print(f"\n{warn}\n")

    while True:
        try:
            question = input("\n❓ Your question: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nGoodbye!")
            break

        if not question:
            continue

        if question.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        if question.lower() == "help":
            print("\nExample questions:")
            for i, q in enumerate(EXAMPLE_QUESTIONS, 1):
                print(f"  {i:2}. {q}")
            continue

        print("\n🔍 Searching HR policies...")
        result = rag.query(question)
        print(f"\n✅ Answer:\n{result['answer']}")
        print(pretty_sources(result["sources"]))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HR Policy Q&A Bot — Ask questions about company policies"
    )
    parser.add_argument(
        "--question", "-q",
        type=str,
        default=None,
        help="Single question (non-interactive mode)",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Directory containing HR policy documents (default: data/)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=512,
        help="Document chunk size in tokens (default: 512)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=4,
        help="Number of chunks to retrieve per query (default: 4)",
    )
    args = parser.parse_args()

    print("⚙️  Initialising HR Policy RAG pipeline...")
    rag = HRPolicyRAG(
        data_dir=args.data_dir,
        chunk_size=args.chunk_size,
        top_k=args.top_k,
    )

    if args.question:
        # Non-interactive: single question mode
        warn = ollama_warning()
        if warn:
            print(warn)
        result = rag.query(args.question)
        print(f"\n❓ Question: {args.question}")
        print(f"\n✅ Answer:\n{result['answer']}")
        print(pretty_sources(result["sources"]))
    else:
        run_interactive(rag)


if __name__ == "__main__":
    main()
