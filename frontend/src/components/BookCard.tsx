import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { STATUSES, type Book } from "../lib/types";

interface Props {
  index?: number;
  book: Book;
  reason?: string;
  onOpen(): void;
  onChange(): void;
}

const hue = (title: string) => [...title].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

export default function BookCard({ index = 0, book, reason, onOpen, onChange }: Props) {
  const { me } = useAuth();

  async function toggleFavorite(ev: React.MouseEvent) {
    ev.stopPropagation();
    await api(`/books/${book.id}/favorite`, { method: book.is_favorite ? "DELETE" : "PUT" });
    onChange();
  }

  return (
    <div className="card" style={{ "--i": index } as React.CSSProperties} role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      {book.image_url ? (
        <img src={book.image_url} alt="" loading="lazy" />
      ) : (
        <div className="cover" style={{ "--h": hue(book.title) } as React.CSSProperties}>
          <b>{book.title.trim().charAt(0).toUpperCase()}</b>
          <span>{book.title}</span>
        </div>
      )}
      <div className="meta">
        <div className="title">{book.title}</div>
        <div className="muted">{book.authors.join(", ")}</div>
        {book.status && (
          <div className="badge">
            {STATUSES[book.status]}
            {book.rating ? ` · ${"★".repeat(book.rating)}` : ""}
          </div>
        )}
        {reason && <div className="muted reason">{reason}</div>}
      </div>
      {me && (
        <button className={"heart" + (book.is_favorite ? " on" : "")} title="В избранное" onClick={toggleFavorite}>
          {book.is_favorite ? "♥" : "♡"}
        </button>
      )}
    </div>
  );
}
