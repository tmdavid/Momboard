import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

interface ChatClaim {
  text: string;
  evidence_highlight_ids: number[];
}

interface ChatAnswer {
  claims: ChatClaim[];
  gap: boolean;
  suggested_interview_question: string | null;
  chat_id: number | null;
}

export function ChatPanel() {
  const [question, setQuestion] = useState('');
  const [chatId, setChatId] = useState<number | null>(null);
  const [history, setHistory] = useState<{ role: string; content: any }[]>([]);

  const askMutation = useMutation({
    mutationFn: async (q: string) => {
      const res = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q, chat_id: chatId }),
      });
      if (!res.ok) throw new Error('Chat request failed');
      return res.json() as Promise<ChatAnswer>;
    },
    onSuccess: (data) => {
      if (data.chat_id) setChatId(data.chat_id);
      setHistory((prev) => [
        ...prev,
        { role: 'user', content: question },
        { role: 'assistant', content: data },
      ]);
      setQuestion('');
    },
  });

  const { data: _chatList } = useQuery({
    queryKey: ['chats'],
    queryFn: async () => {
      const res = await fetch('/api/chat', { credentials: 'include' });
      if (!res.ok) return [];
      return res.json();
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim()) return;
    askMutation.mutate(question.trim());
  };

  return (
    <div className="flex flex-col h-full" data-testid="chat-panel">
      {/* Chat history */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {history.length === 0 && (
          <p className="text-gray-400 text-sm text-center mt-8">
            Ask a question about your evidence corpus. Every claim will cite specific highlights.
          </p>
        )}
        {history.map((turn, i) => (
          <div key={i} className={`${turn.role === 'user' ? 'text-right' : ''}`}>
            {turn.role === 'user' ? (
              <div className="inline-block bg-indigo-100 text-indigo-900 px-3 py-2 rounded-lg text-sm max-w-[80%]">
                {turn.content}
              </div>
            ) : (
              <div className="text-sm space-y-2">
                {(turn.content as ChatAnswer).gap ? (
                  <div className="p-3 bg-amber-50 border border-amber-200 rounded" data-testid="gap-state">
                    <p className="font-medium text-amber-800">No evidence found</p>
                    {(turn.content as ChatAnswer).suggested_interview_question && (
                      <p className="text-amber-700 mt-1 text-xs">
                        💡 Ask next: "{(turn.content as ChatAnswer).suggested_interview_question}"
                      </p>
                    )}
                  </div>
                ) : (
                  (turn.content as ChatAnswer).claims.map((claim, ci) => (
                    <div key={ci} className="p-2 bg-gray-50 rounded">
                      <p>{claim.text}</p>
                      <div className="flex gap-1 mt-1 flex-wrap">
                        {claim.evidence_highlight_ids.map((hid) => (
                          <CitationChip key={hid} highlightId={hid} />
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        ))}
        {askMutation.isPending && (
          <div className="text-sm text-gray-400">Thinking...</div>
        )}
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="p-3 border-t flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about your evidence..."
          className="flex-1 px-3 py-2 border rounded text-sm"
          data-testid="chat-input"
        />
        <button
          type="submit"
          disabled={askMutation.isPending || !question.trim()}
          className="px-4 py-2 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-700 disabled:opacity-50"
        >
          Ask
        </button>
      </form>
    </div>
  );
}

function CitationChip({ highlightId }: { highlightId: number }) {
  return (
    <Link
      to={`/conversations?highlight=${highlightId}`}
      className="inline-flex items-center px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs hover:bg-indigo-100"
      data-testid="citation-chip"
    >
      📌 #{highlightId}
    </Link>
  );
}
