export function BuyChecklist({ items }: { items: string[] }) {
  if (!items.length) return null;

  return (
    <div className="ask-script ask-script--warn">
      <p className="ask-script__kicker">If you still buy</p>
      <h3 className="ask-script__title">Checklist before you pay</h3>
      <p className="ask-script__sub">Only continue if you can do every step below.</p>
      <ol className="ask-script__list">
        {items.map((item, i) => (
          <li key={i}>
            <span className="ask-script__num" aria-hidden>
              {i + 1}
            </span>
            <span className="ask-script__text">{item}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
