import { useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";

interface Props {
  mode: "login" | "register";
  onMode(mode: "login" | "register"): void;
}

export default function Auth({ mode, onMode }: Props) {
  const { login, register } = useAuth();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isRegister = mode === "register";

  function validate() {
    if (!isRegister) return "";
    if (!/^[a-zA-Z0-9_]{3,32}$/.test(username.trim()))
      return "Имя пользователя: от 3 до 32 символов, латинские буквы, цифры и _";
    if (password.length < 8) return "Пароль должен быть не короче 8 символов";
    return "";
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    const problem = validate();
    if (problem) return setError(problem);
    setError("");
    setBusy(true);
    try {
      if (isRegister) await register(email.trim(), username.trim(), password);
      else await login(username.trim(), password);
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(false);
  }

  function switchMode() {
    setError("");
    onMode(isRegister ? "login" : "register");
  }

  return (
    <form className="auth" onSubmit={submit}>
      <h2>{isRegister ? "Регистрация" : "Вход"}</h2>
      <input
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder={isRegister ? "Имя пользователя" : "Логин или email"}
        autoComplete="username"
        required
      />
      {isRegister && (
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          autoComplete="email"
          required
        />
      )}
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Пароль"
        autoComplete={isRegister ? "new-password" : "current-password"}
        required
      />
      <div className="error">{error}</div>
      <button className="primary" type="submit" disabled={busy}>
        {isRegister ? "Создать аккаунт" : "Войти"}
      </button>
      <button type="button" className="ghost" onClick={switchMode}>
        {isRegister ? "Уже есть аккаунт? Войти" : "Нет аккаунта? Зарегистрироваться"}
      </button>
    </form>
  );
}
