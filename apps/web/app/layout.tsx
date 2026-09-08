import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG Portfolio Platform",
  description: "A governed, cost-controlled agentic AI platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
