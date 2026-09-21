export type DomainSlug =
  | "hr-policy"
  | "contract-review"
  | "marketing-hub"
  | "techdocs"
  | "it-helpdesk";

export interface Domain {
  slug: DomainSlug;
  apiName: string;
  name: string;
  description: string;
  status: "live" | "stub";
  concepts: string[];
}

export const DOMAINS: Domain[] = [
  {
    slug: "hr-policy",
    apiName: "hr_policy",
    name: "HR Policy Q&A",
    description: "Ask a question and get an answer cited against the real policy document.",
    status: "live",
    concepts: [
      "SimpleDirectoryReader",
      "SentenceSplitter",
      "VectorStoreIndex",
      "source attribution",
    ],
  },
  {
    slug: "contract-review",
    apiName: "contract_review",
    name: "Contract Review Assistant",
    description: "Multi-document chat with memory.",
    status: "stub",
    concepts: ["ChatMemoryBuffer", "CondensePlusContextChatEngine", "streaming"],
  },
  {
    slug: "marketing-hub",
    apiName: "marketing_hub",
    name: "Marketing Content Hub",
    description: "Qdrant-backed content generation with metadata filtering.",
    status: "stub",
    concepts: ["Qdrant collections", "metadata filtering", "template routing"],
  },
  {
    slug: "techdocs",
    apiName: "techdocs",
    name: "TechDocs RAG Pipeline",
    description: "Hybrid search — BM25 + vector search, reranked for precision.",
    status: "stub",
    concepts: ["Milvus Lite", "BM25", "RRF hybrid search", "CrossEncoder reranking"],
  },
  {
    slug: "it-helpdesk",
    apiName: "it_helpdesk",
    name: "IT Helpdesk Agent",
    description: "Multi-tool agent orchestrating a knowledge base, search, and calendar.",
    status: "stub",
    concepts: [
      "LangGraph supervisor pattern",
      "Weaviate embedded",
      "DuckDuckGo",
      "SQLite",
      "Google Calendar",
    ],
  },
];
