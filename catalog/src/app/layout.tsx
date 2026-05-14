import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wake Adapter Catalog",
  description: "Conformance-verified HarnessAdapter implementations for Wake.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="header">
          <h1>Wake Adapter Catalog</h1>
          <p>Conformance-verified adapters for Wake substrate.</p>
        </header>
        <main className="main">{children}</main>
        <footer className="footer">
          <p>
            HarnessAdapter ABI v0.1.0 · Conformance suite{" "}
            <a href="https://github.com/raphaelchristi/wake/tree/main/adapters/conformance">
              wake-test-conformance
            </a>
          </p>
        </footer>
      </body>
    </html>
  );
}
