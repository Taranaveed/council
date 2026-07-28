type Props = {
  onCopy?: () => void;
  onDownload?: () => void;
  primaryHref?: string;
  primaryLabel?: string;
  copyLabel?: string;
  downloadLabel?: string;
};

/** Mobile sticky action bar for export / open-offer CTAs. */
export function StickyExportBar({
  onCopy,
  onDownload,
  primaryHref,
  primaryLabel = 'View offer',
  copyLabel = 'Copy text',
  downloadLabel = 'Download',
}: Props) {
  const hasActions = Boolean(onCopy || onDownload || primaryHref);
  if (!hasActions) return null;

  return (
    <div className="ux-sticky-bar" role="region" aria-label="Quick actions">
      {primaryHref ? (
        <a href={primaryHref} target="_blank" rel="noreferrer" className="ux-sticky-bar__primary">
          {primaryLabel}
        </a>
      ) : null}
      {onCopy ? (
        <button type="button" className="ux-sticky-bar__btn" onClick={onCopy}>
          {copyLabel}
        </button>
      ) : null}
      {onDownload ? (
        <button type="button" className="ux-sticky-bar__btn" onClick={onDownload}>
          {downloadLabel}
        </button>
      ) : null}
    </div>
  );
}
