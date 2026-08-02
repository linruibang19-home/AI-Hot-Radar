"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const MIN_WIDTH = 180;
const MAX_WIDTH = 420;
const DEFAULT_WIDTH = 232;
const STORAGE_KEY = "ahr.sidebar.width";

/**
 * Drag handle for the sidebar.
 *
 * The width lives in a CSS custom property on <html> rather than in React
 * state, so dragging repaints without re-rendering the tree — the sidebar and
 * main column both read `--sidebar-w`. It is restored from localStorage on
 * mount and written back only when the drag ends, so a drag is one write
 * rather than one per pointer move.
 */
export function SidebarResizer() {
  const [dragging, setDragging] = useState(false);
  const widthRef = useRef(DEFAULT_WIDTH);

  const apply = useCallback((width: number) => {
    const clamped = Math.min(Math.max(width, MIN_WIDTH), MAX_WIDTH);
    widthRef.current = clamped;
    document.documentElement.style.setProperty("--sidebar-w", `${clamped}px`);
  }, []);

  useEffect(() => {
    const saved = Number(window.localStorage.getItem(STORAGE_KEY));
    if (Number.isFinite(saved) && saved > 0) {
      apply(saved);
    }
  }, [apply]);

  useEffect(() => {
    if (!dragging) return;

    const onMove = (event: PointerEvent) => {
      event.preventDefault();
      apply(event.clientX);
    };
    const onUp = () => {
      setDragging(false);
      window.localStorage.setItem(STORAGE_KEY, String(widthRef.current));
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    // Suppress text selection across the page while dragging; without it the
    // drag highlights every heading it passes over.
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
    // Disables the width transition: an eased transition during a drag makes
    // the divider visibly lag the pointer.
    document.documentElement.classList.add("sidebar-dragging");

    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      document.documentElement.classList.remove("sidebar-dragging");
    };
  }, [dragging, apply]);

  /** Keyboard resizing: the drag handle must not be mouse-only (WCAG 2.1.1). */
  const onKeyDown = (event: React.KeyboardEvent) => {
    const step = event.shiftKey ? 40 : 12;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      apply(widthRef.current - step);
      window.localStorage.setItem(STORAGE_KEY, String(widthRef.current));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      apply(widthRef.current + step);
      window.localStorage.setItem(STORAGE_KEY, String(widthRef.current));
    } else if (event.key === "Home") {
      event.preventDefault();
      apply(DEFAULT_WIDTH);
      window.localStorage.setItem(STORAGE_KEY, String(DEFAULT_WIDTH));
    }
  };

  return (
    <div
      className={dragging ? "sidebar-resizer sidebar-resizer-active" : "sidebar-resizer"}
      onPointerDown={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDoubleClick={() => {
        apply(DEFAULT_WIDTH);
        window.localStorage.setItem(STORAGE_KEY, String(DEFAULT_WIDTH));
      }}
      onKeyDown={onKeyDown}
      role="separator"
      aria-orientation="vertical"
      aria-label="调整侧边栏宽度（方向键调整，Home 复位）"
      tabIndex={0}
    >
      <span className="sidebar-resizer-grip" aria-hidden="true" />
    </div>
  );
}
