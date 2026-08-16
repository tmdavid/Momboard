import { useState, useRef, useCallback, useEffect } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { useConversationEvents } from '../hooks/useConversationEvents';

interface Props {
  onClose: () => void;
  onCreated: (id: number) => void;
}

export function NewConversationModal({ onClose, onCreated }: Props) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 16));
  const [interviewer, setInterviewer] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [contactName, setContactName] = useState('');
  const [dealStage, setDealStage] = useState('discovery');
  const [segment, setSegment] = useState('enterprise');
  const [transcript, setTranscript] = useState('');
  const [detectedFormat, setDetectedFormat] = useState('');
  const [createdId, setCreatedId] = useState<number | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  // Track SSE events after creation
  useConversationEvents(createdId, () => {
    queryClient.invalidateQueries({ queryKey: ['conversations'] });
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.createConversation({
        title,
        happened_at: date ? new Date(date).toISOString() : undefined,
        interviewer: interviewer || undefined,
        company: companyName ? { name: companyName } : undefined,
        contacts: contactName ? [{ name: contactName }] : [],
        transcript,
        transcript_format: detectedFormat || undefined,
        meta: { deal_stage: dealStage, segment },
      }),
    onSuccess: (result) => {
      setCreatedId(result.id);
      // Optimistic insert into cache
      queryClient.invalidateQueries({ queryKey: ['conversations'] });
      onCreated(result.id);
    },
  });

  const handleTranscriptChange = useCallback((value: string) => {
    setTranscript(value);
    if (value.startsWith('WEBVTT')) setDetectedFormat('vtt');
    else if (/^\w+\s*:/.test(value)) setDetectedFormat('labeled');
    else setDetectedFormat('');
  }, []);

  const handleFileDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const file = e.dataTransfer.files[0];
      if (file) {
        file.text().then((text) => handleTranscriptChange(text));
      }
    },
    [handleTranscriptChange],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        file.text().then((text) => handleTranscriptChange(text));
      }
    },
    [handleTranscriptChange],
  );

  return (
    <dialog
      ref={dialogRef}
      className="border-none rounded-[14px] p-0 w-[640px] max-w-[92vw] shadow-xl backdrop:bg-ink/35"
      onClose={onClose}
    >
      <div className="flex justify-between items-center px-5 py-4 border-b border-hairline">
        <h2 className="text-base font-semibold">New conversation</h2>
        <button className="text-lg text-muted cursor-pointer bg-transparent border-none" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className="p-5 grid grid-cols-2 gap-3">
        <div className="col-span-2 flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Title</label>
          <input
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            placeholder="Acme Watches — discovery call"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Date</label>
          <input
            type="datetime-local"
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Interviewer</label>
          <input
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            value={interviewer}
            onChange={(e) => setInterviewer(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Company</label>
          <input
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            placeholder="Type to search or create…"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Contact(s)</label>
          <input
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            placeholder="Jane Doe — Brand Manager"
            value={contactName}
            onChange={(e) => setContactName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Deal stage</label>
          <select
            className="px-2 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            value={dealStage}
            onChange={(e) => setDealStage(e.target.value)}
          >
            <option>discovery</option>
            <option>evaluation</option>
            <option>customer</option>
            <option>churned</option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">Plan / segment</label>
          <select
            className="px-2 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            value={segment}
            onChange={(e) => setSegment(e.target.value)}
          >
            <option>enterprise</option>
            <option>mid-market</option>
            <option>smb</option>
          </select>
        </div>
        <div className="col-span-2 flex flex-col gap-1">
          <label className="text-xs font-semibold text-ink-2">
            Transcript{' '}
            {detectedFormat && (
              <span className="text-accent font-semibold">
                · detected: {detectedFormat === 'vtt' ? 'VTT' : 'Name: text'}
              </span>
            )}
          </label>
          <textarea
            className="min-h-[130px] resize-y px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink font-mono text-xs"
            placeholder={`Paste the transcript here…\n\nDavid: How are you handling infringing listings today?\nJane: Honestly, every Monday I export everything to Excel…`}
            value={transcript}
            onChange={(e) => handleTranscriptChange(e.target.value)}
          />
          <div
            className="border-2 border-dashed border-hairline rounded-lg p-2 text-center text-muted text-xs cursor-pointer"
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleFileDrop}
            onClick={() => document.getElementById('file-input')?.click()}
          >
            …or drop a .txt / .vtt file
          </div>
          <input id="file-input" type="file" accept=".txt,.vtt" className="hidden" onChange={handleFileInput} />
        </div>
        <p className="col-span-2 text-xs text-muted">
          On save, MomBoard normalizes speakers, tags Mom Test signals, and runs the analysis — you'll see progress
          live in the table.
        </p>
      </div>

      <div className="flex justify-end gap-2 px-5 py-3.5 border-t border-hairline">
        <button className="btn btn-ghost" onClick={onClose}>
          Cancel
        </button>
        <button
          className="btn btn-primary"
          disabled={!title || !transcript || createMutation.isPending}
          onClick={() => createMutation.mutate()}
        >
          {createMutation.isPending ? 'Creating…' : 'Create & analyze'}
        </button>
      </div>
    </dialog>
  );
}
