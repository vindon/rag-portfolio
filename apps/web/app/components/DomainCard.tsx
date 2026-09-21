import Link from "next/link";
import { StatusBadge } from "./StatusBadge";

interface DomainCardProps {
  name: string;
  description: string;
  status: "live" | "stub";
  href: string;
}

export function DomainCard({ name, description, status, href }: DomainCardProps) {
  return (
    <Link href={href} className="domain-card">
      <StatusBadge status={status} />
      <h3>{name}</h3>
      <p>{description}</p>
    </Link>
  );
}
