"use client";

import { useState } from "react";

const API_BASE_URL = "https://rag-portfolio-api-w57v.onrender.com";

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
      const response = await fetch(`${API_BASE_URL}/api/v1/hr_policy/ask`, {
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
    <section className="demo">
      <h2>HR Policy Q&amp;A — live demo</h2>
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

      {status === "error" && <p className="error">{errorMessage}</p>}

      {result && (
        <div className="result">
          <p className="answer">{result.answer}</p>
          <p className="provider">via {result.provider_used}</p>
          <details>
            <summary>{result.sources.length} source(s)</summary>
            <ul>
              {result.sources.map((source, i) => (
                <li key={i}>
                  <strong>{source.header}</strong> ({source.relevance.toFixed(2)})
                  <br />
                  {source.excerpt}
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  );
}
