import { useEffect, useState } from "react";
import { api } from "../lib/api";
import type { Page, Recommendation } from "../lib/types";
import BookCard from "./BookCard";
import BookDialog from "./BookDialog";

export default function Recs() {
  const [history, setHistory] = useState<Recommendation[] | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);

  async function load() {
    setHistory((await api<Page<Recommendation>>("/recommendations?limit=20")).items);
  }
  useEffect(() => {
    load();
  }, []);

  return (
    <>
      {history && !history.length && (
        <p className="muted">Здесь появятся книги, которые подобрал помощник. Начните разговор во вкладке «Чат».</p>
      )}

      {history?.map((rec) => (
        <section className="rec" key={rec.id}>
          <div className="muted">{new Date(rec.created_at).toLocaleString()}</div>
          <h3>{rec.query.length > 200 ? rec.query.slice(0, 200) + "…" : rec.query}</h3>
          {rec.answer && <p className="plain">{rec.answer}</p>}
          <div className="grid">
            {rec.items.map((item, i) => (
              <BookCard
                key={item.book.id}
                index={i}
                book={item.book}
                reason={item.reason}
                stores={item.stores}
                onOpen={() => setOpenId(item.book.id)}
                onChange={load}
              />
            ))}
          </div>
        </section>
      ))}

      {openId !== null && <BookDialog id={openId} onClose={() => { setOpenId(null); load(); }} />}
    </>
  );
}
