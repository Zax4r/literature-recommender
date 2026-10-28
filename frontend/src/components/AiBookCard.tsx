import type { AiBook } from "../lib/types";

export default function AiBookCard({ book, index }: { book: AiBook; index: number }) {
  return (
    <article className="ai-card" style={{ "--i": index } as React.CSSProperties}>
      <h3>{book.title}</h3>
      <div className="muted">{book.author}</div>
      <div className="chips">
        {[...book.genres.slice(0, 3), ...book.tropes.slice(0, 3)].map((t) => (
          <span className="chip" key={t}>{t}</span>
        ))}
      </div>
      {book.description && <p>{book.description}</p>}
      {book.stores.length > 0 && (
        <div className="stores">
          {book.stores.map((s) => (
            <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">
              {s.name}{s.kind === "ebook" ? " · e-book" : ""}
            </a>
          ))}
        </div>
      )}
    </article>
  );
}
