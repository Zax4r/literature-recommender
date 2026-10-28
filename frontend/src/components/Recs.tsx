import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Page, Recommendation } from "../lib/types";
import BookCard from "./BookCard";
import BookDialog from "./BookDialog";

export default function Recs() {
  const [history, setHistory] = useState<Recommendation[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);

  async function load() {
    setHistory((await api<Page<Recommendation>>("/recommendations?limit=20")).items);
  }
  useEffect(() => {
    load();
  }, []);

  async function send(request: Promise<unknown>) {
    setError("");
    try {
      await request;
      setQuery("");
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  function sendFile(ev: React.ChangeEvent<HTMLInputElement>) {
    const file = ev.target.files?.[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    send(api("/recommendations/file", { method: "POST", body }));
    ev.target.value = "";
  }

  return (
    <>
      <textarea
        rows={3}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Опишите, что хотите почитать, или назовите книгу, на которую хотите быть похожей"
      />
      <div className="row">
        <button
          className="primary"
          disabled={!query.trim()}
          onClick={() => send(api("/recommendations", { method: "POST", json: { query: query.trim() } }))}
        >
          Подобрать
        </button>
        <label className="muted">
          Загрузить .txt <input type="file" accept=".txt,text/plain" onChange={sendFile} className="plain-file" />
        </label>
      </div>
      <div className="error">{error}</div>

      {history.map((rec) => (
        <section className="rec" key={rec.id}>
          <div className="muted">{new Date(rec.created_at).toLocaleString()}</div>
          <div>{rec.query.length > 200 ? rec.query.slice(0, 200) + "…" : rec.query}</div>
          {rec.items.length ? (
            <div className="grid">
              {rec.items.map((item, i) => (
                <BookCard key={item.book.id} index={i} book={item.book} reason={item.reason} onOpen={() => setOpenId(item.book.id)} onChange={load} />
              ))}
            </div>
          ) : (
            <div className="muted">Ничего не нашлось. Попробуйте другие слова.</div>
          )}
        </section>
      ))}

      {openId !== null && <BookDialog id={openId} onClose={() => { setOpenId(null); load(); }} />}
    </>
  );
}
