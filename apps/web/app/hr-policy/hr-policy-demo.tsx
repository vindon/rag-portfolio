"use client";

import { useState } from "react";
import { SourceCard } from "../components/SourceCard";
import { DOMAINS } from "../domains";

const API_BASE_URL = "https://rag-portfolio-api-w57v.onrender.com";
const domain = DOMAINS.find((d) => d.slug === "hr-policy")!;

interface Source {
  header: string;
  excerpt: string;
  relevance: number;
}

interface AskResponse {
  answer: string;
  sources: Source[];
  provider_used: string;
}

export function HrPolicyDemo() {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [result, setResult] = useState<AskResponse | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;

    setStatus("loading");
    setErrorMessage("");
    setResult(null);

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/${domain.apiName}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail ?? `Request failed (${response.status})`);
      }

      const data: AskResponse = await response.json();
      setResult(data);
      setStatus("idle");
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Something went wrong");
      setStatus("error");
    }
  }

  return (
    <div className="demo-card">
      <form onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about HR policy..."
          disabled={status === "loading"}
        />
        <button type="submit" disabled={status === "loading" || !question.trim()}>
          {status === "loading" ? "Asking..." : "Ask"}
        </button>
      </form>

      {status === "error" && <p className="demo-error">{errorMessage}</p>}

      {result && (
        <div>
          <p className="answer">{result.answer}</p>
          <p className="provider-tag">answered via {result.provider_used}</p>
          <div className="sources">
            <div className="sources-label">{result.sources.length} source(s)</div>
            {result.sources.map((source, i) => (
              <SourceCard
                key={i}
                index={i + 1}
                header={source.header}
                excerpt={source.excerpt}
                relevance={source.relevance}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
