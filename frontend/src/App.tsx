import { useEffect, useState } from "react";
import Auth from "./components/Auth";
import Books from "./components/Books";
import Chat from "./components/Chat";
import Hero from "./components/Hero";
import Recs from "./components/Recs";
import { useAuth } from "./lib/auth";

type Tab = "chat" | "feed" | "favorites" | "library" | "recs";
const TABS: [Tab, string][] = [
  ["chat", "Чат"],
  ["feed", "Лента"],
  ["favorites", "Избранное"],
  ["library", "Библиотека"],
  ["recs", "Рекомендации"],
];

export default function App() {
  const { me, ready, logout } = useAuth();
  const [tab, setTab] = useState<Tab>("chat");
  const [authMode, setAuthMode] = useState<"login" | "register" | null>(null);

  // Chat and personal tabs need an account; the public feed does not.
  useEffect(() => {
    if (ready && !me && tab !== "feed") setTab("feed");
  }, [ready, me, tab]);
  useEffect(() => {
    if (me) setAuthMode(null);
  }, [me]);

  let view;
  if (authMode && !me) view = <Auth mode={authMode} onMode={setAuthMode} />;
  else if (tab === "chat" && me) view = <Chat />;
  else if (tab === "recs" && me) view = <div className="page"><Recs /></div>;
  else {
    const kind = tab === "favorites" || tab === "library" ? tab : "feed";
    view = (
      <div className="page">
        {!me && kind === "feed" && <Hero onRegister={() => setAuthMode("register")} onLogin={() => setAuthMode("login")} />}
        <Books key={kind} kind={kind} />
      </div>
    );
  }

  return (
    <>
      <div className="bg" aria-hidden="true"><i /><i /><i /></div>
      <header className="topbar">
        <h1><span className="logo">📚</span><span className="brand">Литература</span></h1>
        <nav>
          {TABS.filter(([id]) => me || id === "feed").map(([id, label]) => (
            <button
              key={id}
              className={"ghost" + (tab === id && !authMode ? " active" : "")}
              onClick={() => { setTab(id); setAuthMode(null); }}
            >
              {label}
            </button>
          ))}
        </nav>
        {me ? (
          <>
            <span className="muted">{me.username}</span>
            <button onClick={logout}>Выйти</button>
          </>
        ) : (
          <>
            <button onClick={() => setAuthMode("login")}>Войти</button>
            <button className="primary" onClick={() => setAuthMode("register")}>Регистрация</button>
          </>
        )}
      </header>
      <main key={authMode ?? tab} className="view">{view}</main>
    </>
  );
}
