import type { Metadata } from "next";
import { AppShell } from "../components/AppShell";
import { StubDomainPage } from "../components/StubDomainPage";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "it-helpdesk")!;

export const metadata: Metadata = {
  title: domain.name,
  description: domain.description,
};

export default function ItHelpdeskPage() {
  return (
    <AppShell>
      <StubDomainPage
        name={domain.name}
        description={domain.description}
        concepts={domain.concepts}
      />
    </AppShell>
  );
}
