import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { STATUSES, type BookDetail, type Tag } from "../lib/types";

export default function BookDialog({ id, onClose }: { id: number; onClose(): void }) {
  const { me } = useAuth();
  const [book, setBook] = useState<BookDetail | null>(null);
  const [tags, setTags] = useState<Tag[]>([]);
  const [newTag, setNewTag] = useState("");
  const [tagError, setTagError] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);

  const load = useCallback(async () => {
    const data = await api<BookDetail>(`/books/${id}`);
    setBook(data);
    setTags(data.tags);
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (book && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [book]);

  async function vote(tag: Tag, value: 1 | -1) {
    const path = `/books/${id}/tags/${encodeURIComponent(tag.name)}/vote`;
    setTags(await api<Tag[]>(path, tag.my_vote === value ? { method: "DELETE" } : { method: "PUT", json: { value } }));
  }

  async function addTag() {
    if (!newTag.trim()) return;
    setTagError("");
    try {
      setTags(await api<Tag[]>(`/books/${id}/tags`, { method: "POST", json: { name: newTag } }));
      setNewTag("");
    } catch (e) {
      setTagError((e as Error).message);
    }
  }

  async function saveEntry(status: string, rating: string) {
    if (!status) await api(`/books/${id}/entry`, { method: "DELETE" });
    else await api(`/books/${id}/entry`, { method: "PUT", json: { status, rating: rating ? +rating : null } });
    await load();
  }

  async function toggleFavorite() {
    await api(`/books/${id}/favorite`, { method: book!.is_favorite ? "DELETE" : "PUT" });
    await load();
  }

  return (
    <dialog ref={dialog} className="book-dialog" onClose={onClose}>
      {book && (
        <>
          <div className="head">
            {book.image_url && <img src={book.image_url} alt="" />}
            <div>
              <h2>{book.title}</h2>
              <div className="muted">{book.authors.join(", ")}</div>
              <p>{book.description.length >= 250 ? book.description + "…" : book.description}</p>
            </div>
          </div>

          <div className="chips">
            {tags.map((tag) => (
              <span className="tag" key={tag.name}>
                {tag.name} {tag.score}
                {me && (
                  <>
                    <button className={tag.my_vote === 1 ? "on" : ""} title="За" onClick={() => vote(tag, 1)}>▲</button>
                    <button className={tag.my_vote === -1 ? "on" : ""} title="Против" onClick={() => vote(tag, -1)}>▼</button>
                  </>
                )}
              </span>
            ))}
          </div>

          {me && (
            <>
              <div className="row">
                <input
                  style={{ width: 200 }}
                  value={newTag}
                  placeholder={tagError || "Предложить тег"}
                  onChange={(e) => setNewTag(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addTag()}
                />
                <button onClick={addTag}>+</button>
              </div>
              <div className="row">
                <select value={book.status ?? ""} onChange={(e) => saveEntry(e.target.value, String(book.rating ?? ""))}>
                  <option value="">На полку</option>
                  {Object.entries(STATUSES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                <select value={String(book.rating ?? "")} disabled={!book.status} onChange={(e) => saveEntry(book.status!, e.target.value)}>
                  <option value="">Оценка</option>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{"★".repeat(n)}</option>)}
                </select>
                <button onClick={toggleFavorite}>{book.is_favorite ? "♥ Убрать из избранного" : "♡ В избранное"}</button>
              </div>
            </>
          )}

          <div className="row">
            <a href={book.store_url} target="_blank" rel="noopener noreferrer">Найти в магазине</a>
            {book.url && <a href={book.url} target="_blank" rel="noopener noreferrer">Goodreads</a>}
            <button style={{ marginLeft: "auto" }} onClick={() => dialog.current?.close()}>Закрыть</button>
          </div>
        </>
      )}
    </dialog>
  );
}
