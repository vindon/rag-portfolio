"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { DOMAINS } from "../domains";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <>
      <nav className="shell-nav">
        <Link href="/" data-active={pathname === "/" ? "true" : "false"}>
          RAG Portfolio
        </Link>
        {DOMAINS.map((d) => (
          <Link
            key={d.slug}
            href={`/${d.slug}`}
            data-active={pathname === `/${d.slug}` ? "true" : "false"}
          >
            {d.name}
          </Link>
        ))}
      </nav>
      <main>{children}</main>
    </>
  );
}
