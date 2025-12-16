import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { I18nProvider } from "@/context/I18nContext";
import CookieConsent from "@/components/CookieConsent"
import { AppEnvProvider } from "@/context/AppEnvContext";
import { normalizeAppEnv } from "@/lib/appEnv";
import { AppEnvBadge } from "@/components/AppEnvBadge";


const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Ascentia Subs",
  description: "AI subtitle workflow for Greek video",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const appEnv = normalizeAppEnv(process.env.APP_ENV ?? process.env.ENV);

  return (
    <html lang="el" suppressHydrationWarning data-app-env={appEnv}>
      <body className={inter.className}>
        <I18nProvider>
          <AppEnvProvider appEnv={appEnv}>
            <AuthProvider>
              <AppEnvBadge />
              {children}
              <CookieConsent />
            </AuthProvider>
          </AppEnvProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
