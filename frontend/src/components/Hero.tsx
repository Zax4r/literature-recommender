export default function Hero({ onRegister, onLogin }: { onRegister(): void; onLogin(): void }) {
  return (
    <section className="hero">
      <span className="float f1" aria-hidden="true">📖</span>
      <span className="float f2" aria-hidden="true">✨</span>
      <span className="float f3" aria-hidden="true">🌙</span>
      <h2>Книга <em>под настроение</em></h2>
      <p>Расскажите помощнику, что хочется почитать, и он подберёт книги и подскажет, где их найти. Все ваши беседы сохраняются.</p>
      <div className="row center">
        <button className="primary big" onClick={onRegister}>Начать бесплатно</button>
        <button className="big" onClick={onLogin}>Войти</button>
      </div>
    </section>
  );
}
