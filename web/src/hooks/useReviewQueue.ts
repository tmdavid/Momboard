import { useState, useCallback, useMemo } from 'react';
import { Highlight } from '../api';

/**
 * Hook to manage the review queue navigation.
 * Provides j/k navigation through suggested highlights.
 */
export function useReviewQueue(suggestedHighlights: Highlight[]) {
  const [currentIdx, setCurrentIdx] = useState(-1);

  const pending = useMemo(
    () => suggestedHighlights.filter((h) => h.status === 'suggested'),
    [suggestedHighlights],
  );

  const currentHighlight = currentIdx >= 0 && currentIdx < pending.length ? pending[currentIdx] : null;

  const focusNext = useCallback(() => {
    setCurrentIdx((prev) => {
      if (pending.length === 0) return -1;
      return Math.min(prev + 1, pending.length - 1);
    });
  }, [pending.length]);

  const focusPrev = useCallback(() => {
    setCurrentIdx((prev) => Math.max(prev - 1, 0));
  }, []);

  return { currentIdx, focusNext, focusPrev, currentHighlight, total: pending.length };
}
