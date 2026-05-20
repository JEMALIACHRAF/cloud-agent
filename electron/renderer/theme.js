import { useState, useEffect, useCallback } from "react";

/**
 * Theme system — light/dark.
 *
 * Sets `data-theme="light"` or `data-theme="dark"` on <html>.
 * Components that use `var(--xxx)` will switch automatically.
 *
 * Stored in localStorage as `ca_theme`.
 */

export function getStoredTheme() {
  try { return localStorage.getItem("ca_theme") || "dark"; } catch { return "dark"; }
}

export function applyTheme(name) {
  document.documentElement.dataset.theme = name;
  try { localStorage.setItem("ca_theme", name); } catch {}
}

export function useTheme() {
  const [theme, setTheme] = useState(getStoredTheme);

  useEffect(() => { applyTheme(theme); }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme(t => t === "dark" ? "light" : "dark");
  }, []);

  return { theme, setTheme, toggleTheme };
}
