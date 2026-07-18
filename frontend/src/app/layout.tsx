import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { I18nProvider } from "@/context/I18nContext";
import CookieConsent from "@/components/CookieConsent"
import { AppEnvProvider } from "@/context/AppEnvContext";
import { normalizeAppEnv } from "@/lib/appEnv";
import { AppEnvBadge } from "@/components/AppEnvBadge";
import { PointsProvider } from "@/context/PointsContext";
import { PwaRegistration } from "@/components/PwaRegistration";


const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  applicationName: "Subframe",
  title: {
    default: "Subframe · Subtitle Studio",
    template: "%s · Subframe",
  },
  description: "Mobile-first subtitle studio for Greek and multilingual short-form video.",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Subframe",
  },
  icons: {
    icon: "/icon.png",
    apple: "/icon.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#f7f7f5",
};

export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const appEnv = normalizeAppEnv(process.env.APP_ENV ?? process.env.ENV);

  return (
    <html lang="el" suppressHydrationWarning data-app-env={appEnv} data-scroll-behavior="smooth">
      <body className={inter.className}>
        <I18nProvider>
          <AppEnvProvider appEnv={appEnv}>
            <AuthProvider>
              <PointsProvider>
                <AppEnvBadge />
                <PwaRegistration />
                {children}
                <CookieConsent />
              </PointsProvider>
            </AuthProvider>
          </AppEnvProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
