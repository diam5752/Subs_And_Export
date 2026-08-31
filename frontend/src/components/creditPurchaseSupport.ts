import type { ConsumerContract } from "./creditPurchaseTypes";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "summary",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export function isAllowedStripeCheckoutUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.origin === "https://checkout.stripe.com" &&
      url.username === "" &&
      url.password === ""
    );
  } catch {
    return false;
  }
}

export function checkoutIdempotencyKey(): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `checkout-${random}`;
}

export function contractDisclosureIdentity(contract: ConsumerContract): string {
  return JSON.stringify([
    contract.disclosure_id,
    contract.disclosure_sha256,
    contract.locale,
    contract.policy_version,
    contract.terms_version,
    contract.withdrawal_notice_version,
  ]);
}

export function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(
    container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
  ).filter(
    (element) =>
      !element.hasAttribute("hidden") &&
      element.getAttribute("aria-hidden") !== "true",
  );
}

export function packageIndexForKey(
  key: string,
  currentIndex: number,
  packageCount: number,
): number | null {
  if (key === "ArrowRight" || key === "ArrowDown") {
    return (currentIndex + 1) % packageCount;
  }
  if (key === "ArrowLeft" || key === "ArrowUp") {
    return (currentIndex - 1 + packageCount) % packageCount;
  }
  if (key === "Home") return 0;
  if (key === "End") return packageCount - 1;
  return null;
}
