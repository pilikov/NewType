import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Font Releases",
  description: "Daily font release feed"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
