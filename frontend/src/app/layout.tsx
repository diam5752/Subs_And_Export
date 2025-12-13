import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { I18nProvider } from "@/context/I18nContext";
import CookieConsent from "@/components/CookieConsent"


const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Greek Sub Publisher",
  description: "AI subtitle workflow for Greek video",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="el" suppressHydrationWarning>
      <body className={inter.className}>
        <I18nProvider>
          <AuthProvider>
            {children}
            <CookieConsent />
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
