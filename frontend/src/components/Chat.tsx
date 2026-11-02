import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, sendChatMessage } from "../lib/api";
import type { ChatMessage, ChatSession, ChatSessionDetail } from "../lib/types";
import AiBookCard from "./AiBookCard";
import BookDialog from "./BookDialog";
import Typewriter from "./Typewriter";

const SUGGESTIONS = [
  "Уютное фэнтези про магию и дружбу",
  "Детектив с неожиданной развязкой",
  "Научная фантастика про космос",
  "Что-нибудь лёгкое на вечер",
];

export default function Chat() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [typingId, setTypingId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [openId, setOpenId] = useState<number | null>(null);
  const [recording, setRecording] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);

  const loadSessions = useCallback(async () => {
    setSessions(await api<ChatSession[]>("/chat/sessions"));
  }, []);
  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  const scrollDown = useCallback(() => {
    requestAnimationFrame(() => scroller.current?.scrollTo({ top: scroller.current.scrollHeight }));
  }, []);

  async function select(id: number) {
    setDrawerOpen(false);
    setError("");
    setTypingId(null);
    const chat = await api<ChatSessionDetail>(`/chat/sessions/${id}`);
    setActiveId(id);
    setMessages(chat.messages);
    scrollDown();
  }

  function newChat() {
    setDrawerOpen(false);
    setActiveId(null);
    setMessages([]);
    setTypingId(null);
    setError("");
  }

  async function rename(chat: ChatSession) {
    const title = prompt("Название чата", chat.title)?.trim();
    if (!title) return;
    await api(`/chat/sessions/${chat.id}`, { method: "PATCH", json: { title } });
    await loadSessions();
  }

  async function remove(chat: ChatSession) {
    if (!confirm(`Удалить чат «${chat.title}»?`)) return;
    await api(`/chat/sessions/${chat.id}`, { method: "DELETE" });
    if (activeId === chat.id) newChat();
    await loadSessions();
  }

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const text = draft.trim();
    if ((!text && !file) || sending) return;
    setSending(true);
    setError("");
    try {
      let id = activeId;
      if (id === null) {
        const chat = await api<ChatSession>("/chat/sessions", { method: "POST" });
        setSessions((s) => [chat, ...s]);
        setActiveId((id = chat.id));
      }
      const attached = file;
      setDraft("");
      setFile(null);
      await sendChatMessage(id, text, attached, {
        onUser: (m) => { setMessages((ms) => [...ms, m]); scrollDown(); },
        onMessage: (m) => { setTypingId(m.id); setMessages((ms) => [...ms, m]); scrollDown(); },
      });
    } catch (err) {
      setError((err as Error).message);
    }
    setSending(false);
    loadSessions();
  }

  async function toggleRecording() {
    if (recorder.current) {
      recorder.current.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        recorder.current = null;
        setRecording(false);
        if (chunks.length) setFile(new File(chunks, "voice.webm", { type: rec.mimeType }));
      };
      rec.start();
      recorder.current = rec;
      setRecording(true);
      setError("");
    } catch {
      setError("Нет доступа к микрофону");
    }
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  const waiting = sending && messages.at(-1)?.role === "user";

  return (
    <div className="chat">
      <aside className={drawerOpen ? "open" : ""}>
        <button className="primary" onClick={newChat}>+ Новый чат</button>
        <ul>
          {sessions.map((chat) => (
            <li key={chat.id} className={chat.id === activeId ? "active" : ""}>
              <button className="ghost title" onClick={() => select(chat.id)}>{chat.title}</button>
              <button className="ghost" title="Переименовать" onClick={() => rename(chat)}>✎</button>
              <button className="ghost" title="Удалить" onClick={() => remove(chat)}>✕</button>
            </li>
          ))}
          {!sessions.length && <li className="muted empty">Пока нет сохранённых чатов</li>}
        </ul>
      </aside>

      <section className="main">
        <button className="ghost burger" onClick={() => setDrawerOpen(!drawerOpen)}>☰ Чаты</button>
        <div className="messages" ref={scroller}>
          {!messages.length && !sending && (
            <div className="hello">
              <span className="float f1" aria-hidden="true">📖</span>
              <span className="float f2" aria-hidden="true">✨</span>
              <h2>Что почитаем?</h2>
              <p className="muted">Расскажите, какую книгу вы ищете: жанр, настроение или похожая история.</p>
              <div className="suggest">
                {SUGGESTIONS.map((s) => <button key={s} onClick={() => setDraft(s)}>{s}</button>)}
              </div>
            </div>
          )}

          {messages.map((m) => (
            <div className={`msg ${m.role}`} key={m.id}>
              <div className="bubble">
                {m.role === "assistant" ? (
                  <Typewriter
                    text={m.content}
                    animate={m.id === typingId}
                    onProgress={scrollDown}
                    onDone={() => { setTypingId(null); scrollDown(); }}
                  />
                ) : (
                  <span className="plain">{m.content}</span>
                )}
              </div>
              {m.id !== typingId && !!m.payload?.recommendations?.length && (
                <div className="cards">
                  {m.payload.recommendations.map((book, i) => <AiBookCard key={i} book={book} index={i} onOpen={setOpenId} />)}
                </div>
              )}
            </div>
          ))}

          {waiting && (
            <div className="msg assistant">
              <div className="bubble typing" aria-label="Помощник печатает"><i /><i /><i /></div>
            </div>
          )}
        </div>

        <div className="error chat-error">{error}</div>
        <form onSubmit={send}>
          {file && (
            <span className="chip file">
              📎 {file.name}
              <button type="button" className="ghost" onClick={() => setFile(null)}>✕</button>
            </span>
          )}
          <div className="composer">
            <label className="attach" title="Прикрепить файл">
              📎
              <input
                type="file"
                hidden
                accept=".txt,.md,.pdf,.docx,audio/*"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); e.target.value = ""; }}
              />
            </label>
            {typeof MediaRecorder !== "undefined" && (
              <button
                type="button"
                className={"mic" + (recording ? " rec" : "")}
                title={recording ? "Остановить запись" : "Голосовой ввод"}
                onClick={toggleRecording}
                disabled={sending}
              >
                🎤
              </button>
            )}
            <textarea
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              placeholder="Что хотите почитать?"
              disabled={sending}
            />
            <button className="primary" type="submit" disabled={sending || typingId !== null || (!draft.trim() && !file)}>
              Отправить
            </button>
          </div>
        </form>
      </section>
      {openId !== null && <BookDialog id={openId} onClose={() => setOpenId(null)} />}
    </div>
  );
}
