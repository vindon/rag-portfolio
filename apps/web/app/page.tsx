import { HrPolicyDemo } from "./hr-policy-demo";

const DOMAINS = [
  { slug: "contract_review", name: "Contract Review Assistant" },
  { slug: "marketing_hub", name: "Marketing Content Hub" },
  { slug: "techdocs", name: "TechDocs RAG Pipeline" },
  { slug: "it_helpdesk", name: "IT Helpdesk Agent" },
];

export default function HomePage() {
  return (
    <main>
      <h1>RAG Portfolio Platform</h1>
      <p>A governed, cost-controlled agentic AI platform.</p>

      <HrPolicyDemo />

      <h2>More domains</h2>
      <ul>
        {DOMAINS.map((domain) => (
          <li key={domain.slug}>{domain.name} — coming online</li>
        ))}
      </ul>
    </main>
  );
}
