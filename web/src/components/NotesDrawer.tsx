import { useState, useRef, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, ApiError } from '../api';
import { renderSafeMarkdown } from '../utils/markdown';

interface Props {
  conversationId: number;
}

export function NotesDrawer({ conversationId }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [preview, setPreview] = useState(false);
  const [body, setBody] = useState('');
  const [saveStatus, setSaveStatus] = useState<'saved' | 'saving' | 'conflict' | 'idle'>('idle');
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string>('');
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const queryClient = useQueryClient();

  const { data: note } = useQuery({
    queryKey: ['note', conversationId],
    queryFn: () => api.getNote(conversationId),
    enabled: !!conversationId,
  });

  // Sync loaded note to state
  useEffect(() => {
    if (note) {
      setBody(note.body_md);
      setLastUpdatedAt(note.updated_at);
      setSaveStatus('saved');
    }
  }, [note]);

  const saveMutation = useMutation({
    mutationFn: (bodyMd: string) =>
      api.putNote(conversationId, { body_md: bodyMd, updated_at: lastUpdatedAt }),
    onSuccess: (result) => {
      setLastUpdatedAt(result.updated_at);
      setSaveStatus('saved');
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        setSaveStatus('conflict');
      } else {
        setSaveStatus('idle');
      }
    },
  });

  const handleChange = useCallback(
    (value: string) => {
      setBody(value);
      setSaveStatus('saving');
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        saveMutation.mutate(value);
      }, 1500);
    },
    [saveMutation],
  );

  const handleReload = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['note', conversationId] });
    setSaveStatus('idle');
  }, [queryClient, conversationId]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  return (
    <div
      className={`flex-none border-t border-hairline bg-surface transition-all flex flex-col overflow-hidden ${
        isOpen ? 'h-[280px]' : 'h-[42px]'
      }`}
    >
      <div
        className="flex items-center gap-2.5 px-5 h-[42px] cursor-pointer flex-none"
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        onClick={() => setIsOpen(!isOpen)}
        onKeyDown={(event) => {
          if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            setIsOpen(!isOpen);
          }
        }}
      >
        <b className="text-[13px]">📝 Notes</b>
        <div className="flex gap-0.5 ml-4" onClick={(e) => e.stopPropagation()}>
          <button
            className={`text-xs px-2.5 py-0.5 rounded-md cursor-pointer ${
              !preview ? 'bg-accent-soft text-accent font-semibold' : 'text-muted'
            }`}
            onClick={() => setPreview(false)}
          >
            Write
          </button>
          <button
            className={`text-xs px-2.5 py-0.5 rounded-md cursor-pointer ${
              preview ? 'bg-accent-soft text-accent font-semibold' : 'text-muted'
            }`}
            onClick={() => setPreview(true)}
          >
            Preview
          </button>
        </div>
        <span className="text-xs text-muted ml-auto">
          {saveStatus === 'saving' && 'Saving…'}
          {saveStatus === 'saved' && 'Saved'}
          {saveStatus === 'conflict' && (
            <span className="text-crit">
              Conflict — someone else edited.{' '}
              <button className="underline cursor-pointer bg-transparent border-none text-crit" onClick={handleReload}>
                Reload
              </button>
            </span>
          )}
        </span>
      </div>

      {!preview ? (
        <textarea
          className="flex-1 border border-hairline rounded-lg outline-none resize-none mx-5 my-3 px-3.5 py-3 font-mono text-[13px] leading-relaxed bg-page text-ink"
          value={body}
          onChange={(e) => handleChange(e.target.value)}
          placeholder="Write notes… markdown supported"
          spellCheck={false}
        />
      ) : (
        <div
          className="flex-1 overflow-auto px-5 py-3.5 border-t border-hairline text-[13.5px] prose prose-sm"
        >
          {body.trim() ? (
            <div dangerouslySetInnerHTML={{ __html: renderSafeMarkdown(body, 'notes') }} />
          ) : (
            <p className="text-muted italic">Nothing to preview yet</p>
          )}
        </div>
      )}
    </div>
  );
}
