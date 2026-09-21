import { AppShell } from "./components/AppShell";
import { DomainCard } from "./components/DomainCard";
import { DOMAINS } from "./domains";

export default function HomePage() {
  return (
    <AppShell>
      <h1>RAG Portfolio Platform</h1>
      <p className="lede">A governed, cost-controlled agentic AI platform.</p>
      <div className="domain-grid">
        {DOMAINS.map((d) => (
          <DomainCard
            key={d.slug}
            name={d.name}
            description={d.description}
            status={d.status}
            href={`/${d.slug}`}
          />
        ))}
      </div>
    </AppShell>
  );
}
