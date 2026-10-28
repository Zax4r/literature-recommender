import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { STATUSES, type Book, type Store } from "../lib/types";

interface Props {
  index?: number;
  book: Book;
  reason?: string;
  stores?: Store[];
  onOpen(): void;
  onChange(): void;
}

const hue = (title: string) => [...title].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

export default function BookCard({ index = 0, book, reason, stores, onOpen, onChange }: Props) {
  const { me } = useAuth();

  async function toggleFavorite(ev: React.MouseEvent) {
    ev.stopPropagation();
    await api(`/books/${book.id}/favorite`, { method: book.is_favorite ? "DELETE" : "PUT" });
    onChange();
  }

  return (
    <div className="card" style={{ "--i": index } as React.CSSProperties} role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <div className="cover" style={{ "--h": hue(book.title) } as React.CSSProperties}>
        <b>{book.title.trim().charAt(0).toUpperCase()}</b>
        <span>{book.title}</span>
      </div>
      <div className="meta">
        <div className="title">{book.title}</div>
        <div className="muted">{book.author.split(";").join(", ")}</div>
        {book.status && (
          <div className="badge">
            {STATUSES[book.status]}
            {book.rating ? ` · ${"★".repeat(book.rating)}` : ""}
          </div>
        )}
        {reason && <div className="muted reason">{reason}</div>}
        {stores && stores.length > 0 && (
          <div className="stores small">
            {stores.map((s) => (
              <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>{s.name}</a>
            ))}
          </div>
        )}
      </div>
      {me && (
        <button className={"heart" + (book.is_favorite ? " on" : "")} title="В избранное" onClick={toggleFavorite}>
          {book.is_favorite ? "♥" : "♡"}
        </button>
      )}
    </div>
  );
}
