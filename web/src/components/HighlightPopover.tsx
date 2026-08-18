import { useEffect, useRef, useState } from 'react';
import { Highlight } from '../api';
import { TAG_META, tagEmoji, tagName } from '../constants';

interface Props {
  highlight: Highlight;
  position: { top: number; left: number };
  onAccept: () => void;
  onReject: () => void;
  onRetag: (newTagKey: string) => void;
  onClose: () => void;
}

export function HighlightPopover({ highlight, position, onAccept, onReject, onRetag, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [selectedTag, setSelectedTag] = useState(highlight.tag_key);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    const handleScroll = () => {
      onClose();
    };
    document.addEventListener('mousedown', handler);
    document.addEventListener('keydown', handleEscape);
    // Close on scroll of transcript or sidebar containers
    const scrollContainers = document.querySelectorAll('[data-scroll-container]');
    scrollContainers.forEach((el) => el.addEventListener('scroll', handleScroll));
    // Also close on window scroll
    window.addEventListener('scroll', handleScroll, true);
    return () => {
      document.removeEventListener('mousedown', handler);
      document.removeEventListener('keydown', handleEscape);
      scrollContainers.forEach((el) => el.removeEventListener('scroll', handleScroll));
      window.removeEventListener('scroll', handleScroll, true);
    };
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="fixed z-20 bg-surface border border-hairline rounded-xl shadow-lg p-3 w-[250px]"
      style={{ top: position.top, left: position.left }}
      role="dialog"
      aria-label="Highlight review"
    >
      <b className="text-[13px]">
        {tagEmoji(highlight.tag_key)} {tagName(highlight.tag_key)}{' '}
        {highlight.status === 'suggested' && (
          <span className="text-muted font-normal">· suggested {highlight.confidence?.toFixed(2)}</span>
        )}
      </b>
      <div className="text-xs text-ink-2 italic my-1.5 line-clamp-2">"{highlight.quote}"</div>
      <select
        className="w-full px-1.5 py-1.5 border border-hairline rounded-lg text-sm mb-2"
        value={selectedTag}
        onChange={(e) => setSelectedTag(e.target.value)}
      >
        {Object.entries(TAG_META).map(([key, meta]) => (
          <option key={key} value={key}>
            {meta.emoji} {meta.name}
          </option>
        ))}
      </select>
      <div className="flex gap-1.5">
        <button
          className="flex-1 py-1.5 rounded-lg bg-[#e6f4e6] text-good-text font-bold text-sm border-none cursor-pointer"
          onClick={() => {
            if (selectedTag !== highlight.tag_key) {
              onRetag(selectedTag);
            } else {
              onAccept();
            }
          }}
        >
          ✓ Accept (a)
        </button>
        <button
          className="flex-1 py-1.5 rounded-lg bg-[#fbe7e7] text-crit font-bold text-sm border-none cursor-pointer"
          onClick={onReject}
        >
          ✕ Reject (x)
        </button>
      </div>
    </div>
  );
}
