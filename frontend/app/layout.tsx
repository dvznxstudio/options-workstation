import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Options Workstation",
  description: "Mobile-first institutional options roadmap"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
