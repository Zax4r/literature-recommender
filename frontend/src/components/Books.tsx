import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { STATUSES, type Book, type Page, type Status } from "../lib/types";
import BookCard from "./BookCard";
import BookDialog from "./BookDialog";

const LIMIT = 12;
const PATHS = { feed: "/books", favorites: "/users/me/favorites", library: "/users/me/library" };

export default function Books({ kind }: { kind: keyof typeof PATHS }) {
  const [items, setItems] = useState<Book[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [status, setStatus] = useState<Status | "">("");
  const [message, setMessage] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const loading = useRef(false);
  const sentinel = useRef<HTMLDivElement>(null);

  const fetchRange = useCallback(
    (offset: number, limit: number) => {
      const extra = kind === "library" && status ? `&status=${status}` : "";
      return api<Page<Book>>(`${PATHS[kind]}?offset=${offset}&limit=${limit}${extra}`);
    },
    [kind, status],
  );

  const loadMore = useCallback(async () => {
    if (loading.current) return;
    loading.current = true;
    try {
      const data = await fetchRange(items.length, LIMIT);
      setItems((prev) => (prev.length === items.length ? [...prev, ...data.items] : prev));
      setTotal(data.total);
      setMessage("");
    } catch (e) {
      setMessage((e as Error).message);
    }
    loading.current = false;
  }, [fetchRange, items.length]);

  // After a change inside a card or dialog, refresh everything already shown.
  const reload = useCallback(async () => {
    try {
      const data = await fetchRange(0, Math.max(items.length, LIMIT));
      setItems(data.items);
      setTotal(data.total);
    } catch (e) {
      setMessage((e as Error).message);
    }
  }, [fetchRange, items.length]);

  useEffect(() => {
    setItems([]);
    setTotal(null);
  }, [status]);

  const hasMore = total === null || items.length < total;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasMore || message) return;
    const observer = new IntersectionObserver((entries) => entries[0].isIntersecting && loadMore(), {
      rootMargin: "400px",
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasMore, loadMore, message]);

  const empty = {
    feed: "Пока здесь нет книг.",
    favorites: "В избранном пока пусто.",
    library: "На полках пока пусто.",
  }[kind];

  return (
    <>
      <div className="row">
        {kind === "library" && (
          <select value={status} onChange={(e) => setStatus(e.target.value as Status | "")}>
            <option value="">Все книги</option>
            {Object.entries(STATUSES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
      </div>

      <div className="muted">{message || (total === 0 ? empty : "")}</div>

      <div className="grid">
        {items.map((book, i) => (
          <BookCard key={book.id} index={i % LIMIT} book={book} onOpen={() => setOpenId(book.id)} onChange={reload} />
        ))}
      </div>
      {hasMore && <div ref={sentinel} className="more muted">Загрузка…</div>}

      {openId !== null && <BookDialog id={openId} onClose={() => { setOpenId(null); reload(); }} />}
    </>
  );
}
