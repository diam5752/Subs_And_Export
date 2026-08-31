import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "GSUBS · Billing reconciliation",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noimageindex: true,
    },
  },
  referrer: "no-referrer",
};

export default function BillingAdminLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
