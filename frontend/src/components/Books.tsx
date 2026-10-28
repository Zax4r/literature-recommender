import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { STATUSES, type Book, type Page, type Status } from "../lib/types";
import BookCard from "./BookCard";
import BookDialog from "./BookDialog";

const LIMIT = 12;
const PATHS = { feed: "/books", favorites: "/users/me/favorites", library: "/users/me/library" };

export default function Books({ kind }: { kind: keyof typeof PATHS }) {
  const { me } = useAuth();
  const [page, setPage] = useState<Page<Book> | null>(null);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<Status | "">("");
  const [message, setMessage] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [importing, setImporting] = useState(false);

  const load = useCallback(async () => {
    try {
      const extra = kind === "library" && status ? `&status=${status}` : "";
      const data = await api<Page<Book>>(`${PATHS[kind]}?offset=${offset}&limit=${LIMIT}${extra}`);
      setPage(data);
      setMessage("");
    } catch (e) {
      setMessage((e as Error).message);
    }
  }, [kind, offset, status]);

  useEffect(() => {
    load();
  }, [load]);

  async function importBooks() {
    setImporting(true);
    setMessage("Обновляем каталог…");
    try {
      const r = await api<{ imported: number }>("/books/sync", { method: "POST" });
      setMessage(r.imported ? `Готово: добавлено книг: ${r.imported}` : "Каталог уже актуален");
      setOffset(0);
      await load();
    } catch (e) {
      setMessage((e as Error).message);
    }
    setImporting(false);
  }

  const empty = {
    feed: me?.is_admin ? "Каталог пуст. Нажмите «Обновить каталог»." : "Пока здесь нет книг.",
    favorites: "В избранном пока пусто.",
    library: "На полках пока пусто.",
  }[kind];

  return (
    <>
      <div className="row">
        {kind === "library" && (
          <select value={status} onChange={(e) => { setStatus(e.target.value as Status | ""); setOffset(0); }}>
            <option value="">Все книги</option>
            {Object.entries(STATUSES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
        {me?.is_admin && kind === "feed" && (
          <button disabled={importing} onClick={importBooks}>Обновить каталог</button>
        )}
      </div>

      <div className="muted">{message || (page && !page.total ? empty : "")}</div>

      {page && (
        <>
          <div className="grid">
            {page.items.map((book, i) => (
              <BookCard key={book.id} index={i} book={book} onOpen={() => setOpenId(book.id)} onChange={load} />
            ))}
          </div>
          <div className="pager">
            <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>← Назад</button>
            <span className="muted">{page.total ? offset + 1 : 0}–{offset + page.items.length} из {page.total}</span>
            <button disabled={offset + LIMIT >= page.total} onClick={() => setOffset(offset + LIMIT)}>Вперёд →</button>
          </div>
        </>
      )}

      {openId !== null && <BookDialog id={openId} onClose={() => { setOpenId(null); load(); }} />}
    </>
  );
}
