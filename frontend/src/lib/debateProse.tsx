import { type ReactNode, useState } from 'react';

/** Turn agent markdown-ish text into clean professional prose (no raw # / *). */

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Bold, italic, inline code — strip markers
  const re = /(\*\*|__)(.+?)\1|(\*|_)(.+?)\3|`([^`]+)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(text.slice(last, m.index));
    }
    if (m[1]) {
      nodes.push(
        <strong key={key++} className="debate-prose__em">
          {m[2]}
        </strong>,
      );
    } else if (m[3]) {
      nodes.push(
        <em key={key++} className="debate-prose__em">
          {m[4]}
        </em>,
      );
    } else if (m[5] !== undefined) {
      nodes.push(
        <span key={key++} className="debate-prose__code">
          {m[5]}
        </span>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function cleanHeading(line: string): string {
  return line.replace(/^#{1,6}\s+/, '').trim();
}

function isBullet(line: string): boolean {
  return /^\s*([-*•]|\d+[.)])\s+/.test(line);
}

function bulletText(line: string): string {
  return line.replace(/^\s*([-*•]|\d+[.)])\s+/, '').trim();
}

type Block =
  | { kind: 'h'; text: string }
  | { kind: 'p'; text: string }
  | { kind: 'ul'; items: string[] };

function parseBlocks(raw: string): Block[] {
  const lines = String(raw || '')
    .replace(/\r\n/g, '\n')
    .replace(/```[\s\S]*?```/g, (block) =>
      block
        .replace(/```(?:\w+)?\n?/g, '')
        .replace(/```/g, '')
        .trim(),
    )
    .split('\n');

  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    if (/^#{1,6}\s+\S/.test(trimmed)) {
      blocks.push({ kind: 'h', text: cleanHeading(trimmed) });
      i += 1;
      continue;
    }
    if (isBullet(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && isBullet(lines[i].trim())) {
        items.push(bulletText(lines[i].trim()));
        i += 1;
      }
      blocks.push({ kind: 'ul', items });
      continue;
    }
    const para: string[] = [trimmed.replace(/^>\s*/, '')];
    i += 1;
    while (i < lines.length) {
      const next = lines[i].trim();
      if (!next || isBullet(next) || /^#{1,6}\s+\S/.test(next)) break;
      para.push(next.replace(/^>\s*/, ''));
      i += 1;
    }
    blocks.push({ kind: 'p', text: para.join(' ') });
  }
  return blocks;
}

export function DebateProse({ text, className = '' }: { text: string; className?: string }) {
  const blocks = parseBlocks(text);
  if (!blocks.length) return null;

  return (
    <div className={`debate-prose ${className}`.trim()}>
      {blocks.map((b, idx) => {
        if (b.kind === 'h') {
          return (
            <p key={idx} className="debate-prose__heading">
              {renderInline(b.text)}
            </p>
          );
        }
        if (b.kind === 'ul') {
          return (
            <ul key={idx} className="debate-prose__list">
              {b.items.map((item, j) => (
                <li key={j}>{renderInline(item)}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={idx} className="debate-prose__p">
            {renderInline(b.text)}
          </p>
        );
      })}
    </div>
  );
}

/** Debate body with Show more when the argument is long. */
export function ExpandableDebate({
  text,
  lines = 8,
  className = '',
}: {
  text: string;
  lines?: number;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const raw = String(text || '').trim();
  if (!raw) return null;
  const long = raw.length > 320 || raw.split(/\n/).filter(Boolean).length > lines;

  return (
    <div className={`ux-expand ${className}`.trim()}>
      <div
        className={`ux-expand__rich${!open && long ? ' ux-expand__text--clamp' : ''}`}
        style={!open && long ? ({ ['--ux-lines' as string]: lines } as never) : undefined}
      >
        <DebateProse text={raw} />
      </div>
      {long ? (
        <button type="button" className="ux-expand__btn" onClick={() => setOpen((v) => !v)}>
          {open ? 'Show less' : 'Show more'}
        </button>
      ) : null}
    </div>
  );
}

/** Plain-string strip for exports / non-React paths. */
export function stripDebateMarkdown(raw: string): string {
  const blocks = parseBlocks(raw);
  return blocks
    .map((b) => {
      if (b.kind === 'h') return b.text.replace(/\*\*|__|\*|_/g, '');
      if (b.kind === 'ul') {
        return b.items.map((it) => `• ${it.replace(/\*\*|__|\*|_/g, '')}`).join('\n');
      }
      return b.text.replace(/\*\*|__|\*|_/g, '').replace(/`([^`]+)`/g, '$1');
    })
    .join('\n\n');
}
