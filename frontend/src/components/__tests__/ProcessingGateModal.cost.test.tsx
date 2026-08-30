import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ProcessingGateModal } from "@/components/ProcessingGateModal";
import { useAuth } from "@/context/AuthContext";

jest.mock("@/context/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@/context/I18nContext", () => ({
  useI18n: () => ({ t: (key: string) => key }),
}));

describe("ProcessingGateModal cost confirmation", () => {
  const onAuthenticated = jest.fn();
  const onConfirm = jest.fn();
  const onClose = jest.fn();
  const onPurchaseCredits = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (useAuth as jest.Mock).mockReturnValue({
      login: jest.fn(),
      register: jest.fn(),
      googleLogin: jest.fn(),
    });
  });

  it("requires an explicit cost confirmation before processing", () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="cost"
        cost={25}
        balance={100}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByText("25")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "processingGateConfirm" }),
    );
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("labels mock processing as local and does not claim an external call", () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="cost"
        cost={25}
        balance={100}
        requiresPaidCredits={false}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(
      screen.getByText("processingGateTotalBalanceLabel"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("processingGateLocalChargeNote"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("processingGateBalanceLabel"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("processingGateChargeNote"),
    ).not.toBeInTheDocument();
  });

  it("routes an insufficient balance to credit purchase without starting processing", () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="cost"
        cost={25}
        balance={10}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
        onPurchaseCredits={onPurchaseCredits}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "processingGateInsufficient",
    );
    expect(
      screen.queryByRole("button", { name: "processingGateConfirm" }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "processingGateBuyCredits" }),
    );
    expect(onPurchaseCredits).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("does not expose a purchase call to action without an approved callback", () => {
    render(
      <ProcessingGateModal
        isOpen
        stage="cost"
        cost={25}
        balance={10}
        isBalanceLoading={false}
        error=""
        onClose={onClose}
        onAuthenticated={onAuthenticated}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "processingGateInsufficient",
    );
    expect(
      screen.queryByRole("button", { name: "processingGateBuyCredits" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "processingGateConfirm" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "processingGateCancel" }),
    ).toBeInTheDocument();
  });
});
