import { useEffect, useRef } from 'react';

/**
 * Hook that connects to the SSE endpoint for a conversation's job progress.
 * Calls onDone when processing completes.
 * Gracefully handles environments where EventSource is unavailable.
 */
export function useConversationEvents(conversationId: number | null, onDone?: () => void) {
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!conversationId) return;
    if (typeof EventSource === 'undefined') return;

    const es = new EventSource(`/api/conversations/${conversationId}/events`);

    es.addEventListener('done', () => {
      onDoneRef.current?.();
      es.close();
    });

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, [conversationId]);
}
