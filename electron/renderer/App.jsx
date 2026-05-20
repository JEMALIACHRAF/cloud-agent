import React, { useState, useEffect } from "react";
import Sidebar      from "./components/Sidebar";
import ChatView     from "./components/ChatView";
import LearnView    from "./components/LearnView";
import AuditView    from "./components/AuditView";
import ManifestView from "./components/ManifestView";
import SettingsView from "./components/SettingsView";
import { useTheme } from "./theme";

function loadSettings() {
  try { return JSON.parse(localStorage.getItem("ca_settings") || "{}"); } catch { return {}; }
}

export default function App() {
  const [view,        setView]        = useState("chat");
  const [settings,    setSettings]    = useState(loadSettings);
  const [userProfile, setUserProfile] = useState({ level: "intermediate", level_confidence: 0 });
  const { theme, toggleTheme } = useTheme();

  const credentials = settings?.creds || {};

  return (
    <div style={{
      display: "flex", height: "100vh", width: "100vw",
      overflow: "hidden", background: "var(--bg)", color: "var(--text)",
    }}>
      <Sidebar
        activeView={view}
        onNavigate={setView}
        userProfile={userProfile}
        theme={theme}
        onToggleTheme={toggleTheme}
      />
      <main style={{ flex: 1, minWidth: 0, height: "100%", overflow: "hidden" }}>
        {view === "chat"     && <ChatView />}
        {view === "learn"    && <LearnView />}
        {view === "audit"    && <AuditView credentials={credentials} />}
        {view === "manifest" && <ManifestView credentials={credentials} />}
        {view === "settings" && <SettingsView onSave={setSettings} />}
      </main>
    </div>
  );
}
