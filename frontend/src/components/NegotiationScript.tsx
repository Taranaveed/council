import { useState } from 'react';

type Props = {
  questions: string[];
  message?: string | null;
};

/** Phase 2 — copy-paste supplier message + short question list. */
export function NegotiationScript({ questions, message }: Props) {
  const [copied, setCopied] = useState(false);
  if (!message && !questions.length) return null;

  const onCopy = async () => {
    if (!message) return;
    try {
      await navigator.clipboard.writeText(message);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* ignore */
    }
  };

  const waHref = message
    ? `https://wa.me/?text=${encodeURIComponent(message)}`
    : null;
  const mailHref = message
    ? `mailto:?subject=${encodeURIComponent('Order inquiry')}&body=${encodeURIComponent(message)}`
    : null;

  return (
    <div className="ask-script">
      {message ? (
        <div className="ask-script__message">
          <p className="ask-script__kicker">Send-ready message</p>
          <h3 className="ask-script__title">Paste this to the supplier</h3>
          <pre className="ask-script__body">{message}</pre>
          <div className="ask-script__actions">
            <button type="button" className="ask-script__btn" onClick={() => void onCopy()}>
              {copied ? 'Copied' : 'Copy message'}
            </button>
            {waHref ? (
              <a href={waHref} target="_blank" rel="noreferrer" className="ask-script__btn ask-script__btn--ghost">
                WhatsApp
              </a>
            ) : null}
            {mailHref ? (
              <a href={mailHref} className="ask-script__btn ask-script__btn--ghost">
                Email
              </a>
            ) : null}
          </div>
        </div>
      ) : null}

      {questions.length > 0 ? (
        <>
          <p className="ask-script__kicker">{message ? 'Also ask' : 'Questions to ask'}</p>
          {!message ? (
            <h3 className="ask-script__title">Ask the seller these before you pay</h3>
          ) : null}
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
        </>
      ) : null}
    </div>
  );
}
