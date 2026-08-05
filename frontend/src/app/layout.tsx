import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { I18nProvider } from "@/context/I18nContext";
import CookieConsent from "@/components/CookieConsent"
import { normalizeAppEnv } from "@/lib/appEnv";
import { PointsProvider } from "@/context/PointsContext";
import { PwaRegistration } from "@/components/PwaRegistration";
import { BRAND } from "@/lib/brand";


const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  applicationName: BRAND.name,
  title: {
    default: BRAND.productTitle,
    template: `%s · ${BRAND.name}`,
  },
  description: BRAND.description,
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: BRAND.name,
  },
  icons: {
    icon: BRAND.assets.icon,
    apple: BRAND.assets.appleIcon,
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
          <AuthProvider>
            <PointsProvider>
              <PwaRegistration />
              {children}
              <CookieConsent />
            </PointsProvider>
          </AuthProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
