import { useEffect, useRef } from 'react';

/**
 * Hook that connects to the SSE endpoint for a conversation's job progress.
 * Calls onDone when processing completes.
 */
export function useConversationEvents(conversationId: number | null, onDone?: () => void) {
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!conversationId) return;

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
