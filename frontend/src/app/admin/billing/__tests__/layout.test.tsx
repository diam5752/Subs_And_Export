import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import BillingAdminLayout, { metadata } from "@/app/admin/billing/layout";

describe("BillingAdminLayout", () => {
  it("keeps the reconciliation surface out of search indexes", () => {
    render(
      <BillingAdminLayout>
        <p>Billing reconciliation</p>
      </BillingAdminLayout>,
    );

    expect(screen.getByText("Billing reconciliation")).toBeInTheDocument();
    expect(metadata).toMatchObject({
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
    });
  });
});
