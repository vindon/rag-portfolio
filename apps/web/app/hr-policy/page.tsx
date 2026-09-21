import { AppShell } from "../components/AppShell";
import { HrPolicyDemo } from "./hr-policy-demo";

export default function HrPolicyPage() {
  return (
    <AppShell>
      <h1>HR Policy Q&amp;A</h1>
      <p>Ask a question and get an answer cited against the real policy document.</p>
      <HrPolicyDemo />
    </AppShell>
  );
}
