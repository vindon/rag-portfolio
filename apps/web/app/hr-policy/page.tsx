import type { Metadata } from "next";
import { AppShell } from "../components/AppShell";
import { HrPolicyDemo } from "./hr-policy-demo";
import { DOMAINS } from "../domains";

const domain = DOMAINS.find((d) => d.slug === "hr-policy")!;

export const metadata: Metadata = {
  title: domain.name,
  description: domain.description,
};

export default function HrPolicyPage() {
  return (
    <AppShell>
      <h1>{domain.name}</h1>
      <p className="lede">{domain.description}</p>
      <HrPolicyDemo />
    </AppShell>
  );
}
