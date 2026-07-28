import { useState, type ReactNode } from 'react';

type Props = {
  children: string;
  lines?: number;
  className?: string;
};

/** Truncate long prose with an inline Show more / Show less control. */
export function ExpandableText({ children, lines = 3, className = '' }: Props) {
  const [open, setOpen] = useState(false);
  const text = String(children || '').trim();
  if (!text) return null;

  const long = text.length > 180 || text.split(/\n/).length > lines;

  return (
    <div className={`ux-expand ${className}`.trim()}>
      <p
        className={`ux-expand__text${open || !long ? '' : ' ux-expand__text--clamp'}`}
        style={open || !long ? undefined : ({ ['--ux-lines' as string]: lines } as never)}
      >
        {text}
      </p>
      {long ? (
        <button type="button" className="ux-expand__btn" onClick={() => setOpen((v) => !v)}>
          {open ? 'Show less' : 'Show more'}
        </button>
      ) : null}
    </div>
  );
}

export function ExpandableNode({
  children,
  preview,
}: {
  children: ReactNode;
  preview: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="ux-expand">
      {open ? children : preview}
      <button type="button" className="ux-expand__btn" onClick={() => setOpen((v) => !v)}>
        {open ? 'Show less' : 'Show more'}
      </button>
    </div>
  );
}
