import { AppShell } from "../components/AppShell";
import { StubDomainPage } from "../components/StubDomainPage";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "marketing-hub")!;

export default function MarketingHubPage() {
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
