import { useEffect, useRef, useState, type ChangeEvent, type CSSProperties, type FormEvent } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { STATUSES, type Status, type UserStats } from "../lib/types";
import Avatar from "./Avatar";

const AVATAR_SIZE = 256;

/** Crops the picked image to a centred square and shrinks it so it stays small to store. */
async function toAvatar(file: File): Promise<string> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const side = Math.min(img.naturalWidth, img.naturalHeight);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = AVATAR_SIZE;
    canvas
      .getContext("2d")!
      .drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
    return canvas.toDataURL("image/jpeg", 0.85);
  } finally {
    URL.revokeObjectURL(url);
  }
}

export default function Profile() {
  const { me, updateProfile } = useAuth();
  const [stats, setStats] = useState<UserStats | null>(null);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const [bio, setBio] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<UserStats>("/users/me/stats").then(setStats).catch((e) => setError((e as Error).message));
  }, []);

  if (!me) return null;
  const shownName = me.display_name || me.username;

  async function save(changes: Parameters<typeof updateProfile>[0]) {
    setError("");
    setBusy(true);
    try {
      await updateProfile(changes);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function pickAvatar(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) return setError("Выберите файл с картинкой");
    let avatar: string;
    try {
      avatar = await toAvatar(file);
    } catch {
      return setError("Не удалось прочитать картинку");
    }
    await save({ avatar });
  }

  function startEditing() {
    setName(me!.display_name ?? "");
    setBio(me!.bio ?? "");
    setError("");
    setEditing(true);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (await save({ display_name: name.trim() || null, bio: bio.trim() || null })) setEditing(false);
  }

  const tiles: [string, string][] = [
    ...(Object.entries(STATUSES) as [Status, string][]).map(([key, label]): [string, string] => [
      label,
      String(stats?.[key] ?? "–"),
    ]),
    ["Избранное", String(stats?.favorites ?? "–")],
    [
      stats ? `Средняя оценка (${stats.rated})` : "Средняя оценка",
      stats?.average_rating != null ? `★ ${stats.average_rating}` : "–",
    ],
  ];

  return (
    <div className="page profile">
      <section className="profile-head">
        <div className="avatar-edit">
          <Avatar name={shownName} src={me.avatar} size={120} />
          <button type="button" className="avatar-btn" onClick={() => picker.current?.click()} disabled={busy}>
            📷 {me.avatar ? "Сменить" : "Добавить фото"}
          </button>
          {me.avatar && (
            <button type="button" className="ghost" onClick={() => save({ avatar: null })} disabled={busy}>
              Убрать
            </button>
          )}
          <input ref={picker} type="file" accept="image/*" hidden onChange={pickAvatar} />
        </div>

        {editing ? (
          <form className="profile-form" onSubmit={submit}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Отображаемое имя" maxLength={64} />
            <textarea value={bio} onChange={(e) => setBio(e.target.value)} placeholder="О себе: что любите читать" rows={4} maxLength={1000} />
            <div className="row">
              <button className="primary" type="submit" disabled={busy}>Сохранить</button>
              <button type="button" className="ghost" onClick={() => setEditing(false)}>Отмена</button>
            </div>
          </form>
        ) : (
          <div className="profile-info">
            <h2>{shownName}</h2>
            <div className="muted">@{me.username} · {me.email}</div>
            <div className="muted">
              С нами с {new Date(me.created_at).toLocaleDateString("ru-RU", { year: "numeric", month: "long" })}
            </div>
            <p className={me.bio ? "plain" : "muted"}>{me.bio || "Расскажите о себе: что любите читать."}</p>
            <button onClick={startEditing}>✏️ Редактировать</button>
          </div>
        )}
      </section>
      <div className="error">{error}</div>

      <h3>Мои книги</h3>
      <div className="stats">
        {tiles.map(([label, value], i) => (
          <div className="stat" key={label} style={{ "--i": i } as CSSProperties}>
            <b>{value}</b>
            <span className="muted">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
