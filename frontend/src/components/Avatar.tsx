import type { CSSProperties } from "react";

interface Props {
  name: string;
  src?: string | null;
  size?: number;
}

const hue = (name: string) => [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);

/** The user's picture, or a coloured circle with the first letter of the name. */
export default function Avatar({ name, src, size = 36 }: Props) {
  const style = { "--size": `${size}px`, "--h": hue(name) } as CSSProperties;
  return src ? (
    <img className="avatar" style={style} src={src} alt="" />
  ) : (
    <span className="avatar letter" style={style} aria-hidden="true">
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}
