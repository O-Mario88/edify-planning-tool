import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { SessionProvider } from "@/components/auth/SessionProvider";
import { DemoShell } from "@/components/demo/DemoShell";
import { ThemeProvider, themePreloadScript } from "@/components/theme/ThemeProvider";

// Plus Jakarta Sans — the modern dashboard typeface. Geometric, friendly,
// with confident headings and crisp tabular numerals; the exact register
// shipped by today's premium sports + fintech dashboards. Replaces Inter.
//
// We keep the legacy --font-source-sans variable name so every CSS file
// that already references it (globals.css → --font-sans) flows through
// to Plus Jakarta Sans without a sweeping rename.
const appFont = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["200", "300", "400", "500", "600", "700", "800"],
  variable: "--font-source-sans",
  display: "swap",
  fallback: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
});

export const metadata: Metadata = {
  title: "Edify · CCEO Dashboard",
  description: "My Monthly Field Work Dashboard — Plan smart. Execute with focus. Lead with impact.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0a1623",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${appFont.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        {/* Pre-paint theme application — must run before React mounts
            so dark-mode users don't see a flash of light content on
            reload. The script reads localStorage + the OS preference
            and stamps `.dark` on <html> synchronously. */}
        <script
          dangerouslySetInnerHTML={{ __html: themePreloadScript }}
        />
      </head>
      <body className="min-h-full flex flex-col bg-[var(--color-page)] text-[var(--color-edify-text)]">
        <a href="#main-content" className="skip-link">Skip to content</a>
        <ThemeProvider>
          <SessionProvider>
            <DemoShell>{children}</DemoShell>
          </SessionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
