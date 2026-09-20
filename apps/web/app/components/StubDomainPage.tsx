import { StatusBadge } from "./StatusBadge";

interface StubDomainPageProps {
  name: string;
  description: string;
  concepts: string[];
}

export function StubDomainPage({ name, description, concepts }: StubDomainPageProps) {
  return (
    <div className="stub-page">
      <StatusBadge status="stub" />
      <h2>{name}</h2>
      <p>{description}</p>
      <ul className="stub-concepts">
        {concepts.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </div>
  );
}
