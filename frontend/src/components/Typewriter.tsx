import { useEffect, useRef, useState } from "react";

interface Props {
  text: string;
  animate: boolean;
  onProgress(): void;
  onDone(): void;
}

/** Reveals the text progressively when `animate` is set, otherwise shows it at once. */
export default function Typewriter({ text, animate, onProgress, onDone }: Props) {
  const [count, setCount] = useState(0);
  const callbacks = useRef({ onProgress, onDone });
  callbacks.current = { onProgress, onDone };

  useEffect(() => {
    if (!animate) return;
    const step = Math.max(1, Math.ceil(text.length / 150));
    let n = 0;
    const timer = setInterval(() => {
      n = Math.min(text.length, n + step);
      setCount(n);
      callbacks.current.onProgress();
      if (n >= text.length) {
        clearInterval(timer);
        callbacks.current.onDone();
      }
    }, 20);
    return () => clearInterval(timer);
  }, [animate, text]);

  return <span className="plain">{animate ? text.slice(0, count) : text}</span>;
}
