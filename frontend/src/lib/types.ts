export type Status = "read" | "reading" | "dropped" | "planned";

export const STATUSES: Record<Status, string> = {
  read: "Прочитано",
  reading: "Читаю",
  dropped: "Брошено",
  planned: "В планах",
};

export interface Me {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
}

export interface Book {
  id: number;
  title: string;
  authors: string[];
  image_url: string | null;
  is_favorite: boolean;
  status: Status | null;
  rating: number | null;
}

export interface Tag {
  name: string;
  score: number;
  my_vote: number;
}

export interface BookDetail extends Book {
  description: string;
  url: string | null;
  store_url: string;
  tags: Tag[];
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface Recommendation {
  id: number;
  query: string;
  source: string;
  created_at: string;
  items: { book: Book; reason: string; store_url: string }[];
}

export interface Store {
  name: string;
  url: string;
  kind: "paper" | "ebook";
}

export interface AiBook {
  title: string;
  author: string;
  genres: string[];
  tropes: string[];
  description: string;
  stores: Store[];
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  payload: { intent?: string; recommendations?: AiBook[] } | null;
  created_at: string;
}

export interface ChatSession {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionDetail extends ChatSession {
  messages: ChatMessage[];
}
