"""
04-techDocs-rag-pipeline/pipeline/evaluate.py

RAG evaluation harness using LlamaIndex's built-in evaluators.

Concepts demonstrated:
  - FaithfulnessEvaluator: is the answer grounded in the retrieved context?
  - RelevancyEvaluator: does the answer address the question?
  - CorrectnessEvaluator: factual accuracy (requires reference answer)
  - Batch evaluation across a test question set
  - Scoring and reporting
"""

import sys
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from llama_index.core.evaluation import (
    FaithfulnessEvaluator,
    RelevancyEvaluator,
)
from llama_index.core.llms import LLM
from llama_index.core.schema import TextNode

from shared.llm_factory import get_llm

logger = logging.getLogger(__name__)


@dataclass
class EvalResult:
    question: str
    answer: str
    faithfulness_score: float        # 1.0 = answer is grounded in context
    faithfulness_pass: bool
    relevancy_score: float           # 1.0 = answer addresses the question
    relevancy_pass: bool
    retrieval_method: str
    sources_used: int
    feedback: str = ""

    @property
    def overall_pass(self) -> bool:
        return self.faithfulness_pass and self.relevancy_pass


class RAGEvaluator:
    """
    Runs faithfulness and relevancy evaluations against a query engine.

    Faithfulness measures hallucination risk:
      "Is every statement in the answer supported by the retrieved context?"

    Relevancy measures answer quality:
      "Does the answer actually address what was asked?"

    Both use the LLM as a judge (LLM-as-judge pattern).
    """

    def __init__(self, judge_llm: Optional[LLM] = None) -> None:
        self.llm = judge_llm or get_llm(temperature=0)
        self.faithfulness_eval = FaithfulnessEvaluator(llm=self.llm)
        self.relevancy_eval = RelevancyEvaluator(llm=self.llm)
        logger.info("RAGEvaluator initialised with LLM judge")

    def evaluate_response(
        self,
        question: str,
        response_obj,
        retrieval_method: str = "hybrid",
    ) -> EvalResult:
        """
        Evaluate a single query-response pair.
        response_obj is the raw LlamaIndex Response object.
        """
        answer = str(response_obj).strip()
        contexts = [node.text for node in response_obj.source_nodes]

        # Faithfulness: answer ↔ context
        try:
            faith = self.faithfulness_eval.evaluate_response(
                query=question,
                response=response_obj,
            )
            faith_score = float(faith.score or 0)
            faith_pass  = faith.passing
            feedback    = faith.feedback or ""
        except Exception as e:
            logger.warning("Faithfulness eval failed: %s", e)
            faith_score, faith_pass, feedback = 0.0, False, str(e)

        # Relevancy: answer ↔ question
        try:
            relev = self.relevancy_eval.evaluate_response(
                query=question,
                response=response_obj,
            )
            relev_score = float(relev.score or 0)
            relev_pass  = relev.passing
        except Exception as e:
            logger.warning("Relevancy eval failed: %s", e)
            relev_score, relev_pass = 0.0, False

        return EvalResult(
            question=question,
            answer=answer,
            faithfulness_score=round(faith_score, 3),
            faithfulness_pass=faith_pass,
            relevancy_score=round(relev_score, 3),
            relevancy_pass=relev_pass,
            retrieval_method=retrieval_method,
            sources_used=len(contexts),
            feedback=feedback,
        )

    def batch_evaluate(
        self,
        questions: List[str],
        query_engine,
        retrieval_method: str = "hybrid",
    ) -> Dict:
        """
        Run evaluation across a list of questions.

        Returns a summary dict with per-question results and aggregate stats.
        """
        results: List[EvalResult] = []

        for i, q in enumerate(questions, 1):
            logger.info("Evaluating %d/%d: %s", i, len(questions), q[:60])
            try:
                response = query_engine.query_engine.query(q)
                result = self.evaluate_response(q, response, retrieval_method)
                results.append(result)
            except Exception as e:
                logger.error("Eval error on question %d: %s", i, e)

        if not results:
            return {"error": "No results generated"}

        avg_faith = sum(r.faithfulness_score for r in results) / len(results)
        avg_relev = sum(r.relevancy_score for r in results) / len(results)
        pass_rate = sum(1 for r in results if r.overall_pass) / len(results)

        return {
            "summary": {
                "questions_evaluated": len(results),
                "avg_faithfulness": round(avg_faith, 3),
                "avg_relevancy": round(avg_relev, 3),
                "overall_pass_rate": round(pass_rate, 3),
            },
            "results": [asdict(r) for r in results],
        }


# ── Default test question set for technical documentation ─────────────────────
DEFAULT_EVAL_QUESTIONS = [
    "How do I authenticate with the DataFlow API?",
    "What is the rate limit for API calls?",
    "How do I configure webhooks for real-time events?",
    "What error code indicates an invalid API key?",
    "How do I set up the SDK for Python?",
    "What data sources can I connect to DataFlow?",
    "How do I create a custom dashboard?",
    "What is the maximum data retention period?",
]
