import { useCallback } from "react";

export function useCredentials() {
  const getCredentials = useCallback(async () => {
    try {
      // First: try localStorage (Settings UI)
      const stored = localStorage.getItem("ca_settings");
      if (stored) {
        const s = JSON.parse(stored);
        if (s?.creds?.aws_access_key_id) return s.creds;
      }
      // Fallback: Electron keychain (if available)
      if (window?.electronAPI?.getCredentials) {
        return await window.electronAPI.getCredentials();
      }
      // Dev fallback: use named profile (backend picks it up)
      return { profile: "default" };
    } catch {
      return {};
    }
  }, []);

  return { getCredentials };
}
