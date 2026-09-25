import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "DocIntel — Multi-Tenant Enterprise Document Intelligence",
  description: "Enterprise RAG platform with hybrid search, verified citations, and token budget governance.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased selection:bg-blue-500 selection:text-white">
        {children}
      </body>
    </html>
  );
}
