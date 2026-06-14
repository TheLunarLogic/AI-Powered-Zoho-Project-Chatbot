import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Zoho Project Chatbot",
  description: "AI-powered assistant for Zoho Projects",
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
