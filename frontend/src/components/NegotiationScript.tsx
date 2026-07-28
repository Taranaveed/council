export function NegotiationScript({ questions }: { questions: string[] }) {
  if (!questions.length) return null;

  return (
    <div className="ask-script">
      <p className="ask-script__kicker">Questions to ask</p>
      <h3 className="ask-script__title">Ask the seller these before you pay</h3>
      <ol className="ask-script__list">
        {questions.map((q, i) => (
          <li key={i}>
            <span className="ask-script__num" aria-hidden>
              {i + 1}
            </span>
            <span className="ask-script__text">{q}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
