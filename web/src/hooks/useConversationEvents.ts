import { useEffect, useRef } from 'react';

/**
 * Hook that connects to the SSE endpoint for a conversation's job progress.
 * Calls onDone when processing completes.
 * Gracefully handles environments where EventSource is unavailable.
 */
export function useConversationEvents(
  conversationId: number | null,
  onDone?: () => void,
  onStage?: (stage: 'normalizing' | 'tagging' | 'analyzing') => void,
) {
  const onDoneRef = useRef(onDone);
  const onStageRef = useRef(onStage);
  onDoneRef.current = onDone;
  onStageRef.current = onStage;

  useEffect(() => {
    if (!conversationId) return;
    if (typeof EventSource === 'undefined') return;

    const es = new EventSource(`/api/conversations/${conversationId}/events`);
    const stageEvents: Array<[string, 'normalizing' | 'tagging' | 'analyzing']> = [
      ['ingest.running', 'normalizing'],
      ['tag.running', 'tagging'],
      ['analyze.running', 'analyzing'],
    ];
    const listeners = stageEvents.map(([event, stage]) => {
      const listener = () => onStageRef.current?.(stage);
      es.addEventListener(event, listener);
      return [event, listener] as const;
    });

    const doneListener = () => {
      onDoneRef.current?.();
      es.close();
    };
    es.addEventListener('done', doneListener);

    // Closing here deliberately leaves the conversation in the Library tracking
    // set, where the query's 5-second refetch interval acts as the fallback.
    es.onerror = () => {
      es.close();
    };

    return () => {
      listeners.forEach(([event, listener]) => es.removeEventListener(event, listener));
      es.removeEventListener('done', doneListener);
      es.close();
    };
  }, [conversationId]);
}
