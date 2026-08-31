"use client";

import { useLayoutEffect } from "react";

interface DocumentScrollPosition {
  x: number;
  y: number;
}

function lockedDocumentScrollPosition(): DocumentScrollPosition {
  const body = document.body;
  if (body.style.position !== "fixed") {
    return { x: window.scrollX, y: window.scrollY };
  }

  const bodyLeft = Number.parseFloat(body.style.left);
  const bodyTop = Number.parseFloat(body.style.top);
  return {
    x: Number.isFinite(bodyLeft) ? -bodyLeft : window.scrollX,
    y: Number.isFinite(bodyTop) ? -bodyTop : window.scrollY,
  };
}

/**
 * Lock both browser scrollers without losing the exact viewport position.
 * Fixing only body overflow still allows the page behind a modal to move in
 * iOS Safari and embedded WebKit browsers.
 */
export function useDocumentScrollLock(
  isLocked: boolean,
  initialScrollPosition?: DocumentScrollPosition,
): void {
  useLayoutEffect(() => {
    if (!isLocked) return;

    const root = document.documentElement;
    const body = document.body;
    const currentPosition = lockedDocumentScrollPosition();
    const scrollX = initialScrollPosition?.x ?? currentPosition.x;
    const scrollY = initialScrollPosition?.y ?? currentPosition.y;
    const previousRootStyles = {
      overflow: root.style.overflow,
      overscrollBehavior: root.style.overscrollBehavior,
      scrollBehavior: root.style.scrollBehavior,
      height: root.style.height,
    };
    const previousBodyStyles = {
      overflow: body.style.overflow,
      overscrollBehavior: body.style.overscrollBehavior,
      position: body.style.position,
      top: body.style.top,
      left: body.style.left,
      width: body.style.width,
      height: body.style.height,
    };
    const restoreLockedPosition = () => {
      if (window.scrollX !== scrollX || window.scrollY !== scrollY) {
        window.scrollTo(scrollX, scrollY);
      }
    };

    root.style.overflow = "hidden";
    root.style.overscrollBehavior = "none";
    root.style.height = "100%";
    body.style.overflow = "hidden";
    body.style.overscrollBehavior = "none";
    body.style.position = "fixed";
    body.style.top = `${-scrollY}px`;
    body.style.left = `${-scrollX}px`;
    body.style.width = "100%";
    body.style.height = "100%";
    window.addEventListener("scroll", restoreLockedPosition, { passive: true });

    return () => {
      window.removeEventListener("scroll", restoreLockedPosition);
      root.style.overflow = previousRootStyles.overflow;
      root.style.overscrollBehavior = previousRootStyles.overscrollBehavior;
      root.style.height = previousRootStyles.height;
      body.style.overflow = previousBodyStyles.overflow;
      body.style.overscrollBehavior = previousBodyStyles.overscrollBehavior;
      body.style.position = previousBodyStyles.position;
      body.style.top = previousBodyStyles.top;
      body.style.left = previousBodyStyles.left;
      body.style.width = previousBodyStyles.width;
      body.style.height = previousBodyStyles.height;

      // The global smooth-scroll rule must not animate modal cleanup.
      root.style.scrollBehavior = "auto";
      window.scrollTo(scrollX, scrollY);
      root.style.scrollBehavior = previousRootStyles.scrollBehavior;
    };
  }, [initialScrollPosition?.x, initialScrollPosition?.y, isLocked]);
}
