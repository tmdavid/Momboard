import { useState, useRef, useCallback, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

export interface NewConversationFormData {
  title: string;
  happened_at?: string;
  interviewer?: string;
  company?: { name: string };
  contacts?: Array<{ name: string; role?: string }>;
  transcript: string;
  transcript_format?: string;
  meta?: Record<string, unknown>;
}

interface Props {
  onClose: () => void;
  onCreated?: (id: number, title: string) => void;
  onSubmit?: (data: NewConversationFormData) => void;
  isSubmitting?: boolean;
}

interface ContactEntry {
  name: string;
  role: string;
}

export function NewConversationModal({ onClose, onCreated, onSubmit, isSubmitting }: Props) {
  const [title, setTitle] = useState('');
  const [date, setDate] = useState(new Date().toISOString().slice(0, 16));
  const [interviewer, setInterviewer] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [companyDropdownOpen, setCompanyDropdownOpen] = useState(false);
  const [contacts, setContacts] = useState<ContactEntry[]>([{ name: '', role: '' }]);
  const [dealStage, setDealStage] = useState('discovery');
  const [segment, setSegment] = useState('enterprise');
  const [transcript, setTranscript] = useState('');
  const [detectedFormat, setDetectedFormat] = useState('');
  const dialogRef = useRef<HTMLDialogElement>(null);

  // Audio upload state
  const [mode, setMode] = useState<'text' | 'audio'>('text');
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [audioUploading, setAudioUploading] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [audioLanguage, setAudioLanguage] = useState('');

  const AUDIO_EXTENSIONS = ['.mp3', '.mp4', '.mpeg', '.mpga', '.m4a', '.wav', '.webm', '.ogg'];

  // Fetch existing companies for the combobox
  const { data: companies } = useQuery({
    queryKey: ['companies'],
    queryFn: () => api.listCompanies(),
  });

  // Fetch conversations to count calls per company
  const { data: conversations } = useQuery({
    queryKey: ['conversations-for-title'],
    queryFn: () => api.listConversations({ limit: 200 }),
  });

  // Auto-suggest title when company or deal stage changes
  const [titleManuallyEdited, setTitleManuallyEdited] = useState(false);

  useEffect(() => {
    if (titleManuallyEdited || !companyName) return;
    const companyConvos = conversations?.items.filter(
      (c) => c.company?.name?.toLowerCase() === companyName.toLowerCase(),
    ) ?? [];
    const callNumber = companyConvos.length + 1;
    setTitle(`${companyName} — ${dealStage} — call ${callNumber}`);
  }, [companyName, dealStage, conversations, titleManuallyEdited]);

  useEffect(() => {
    dialogRef.current?.showModal();
  }, []);

  const handleSubmit = useCallback(() => {
    if (mode === 'audio' && audioFile) {
      // Audio upload via multipart
      setAudioUploading(true);
      setAudioError(null);
      const formData = new FormData();
      formData.append('file', audioFile);
      formData.append('title', title);
      if (interviewer) formData.append('interviewer', interviewer);
      if (audioLanguage) formData.append('language', audioLanguage);

      fetch('/api/conversations/upload', {
        method: 'POST',
        credentials: 'include',
        body: formData,
      })
        .then(async (r) => {
          if (!r.ok) {
            const err = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
            throw new Error(err.detail || `Upload failed (${r.status})`);
          }
          return r.json();
        })
        .then((data) => {
          setAudioUploading(false);
          if (onCreated) {
            onCreated(data.id, data.title);
          } else {
            onClose();
          }
        })
        .catch((err) => {
          setAudioUploading(false);
          setAudioError(err.message);
        });
      return;
    }

    // Text/paste mode
    const formData: NewConversationFormData = {
      title,
      happened_at: date ? new Date(date).toISOString() : undefined,
      interviewer: interviewer || undefined,
      company: companyName ? { name: companyName } : undefined,
      contacts: contacts.filter((c) => c.name).map((c) => ({ name: c.name, role: c.role || undefined })),
      transcript,
      transcript_format: detectedFormat || undefined,
      meta: { deal_stage: dealStage, segment },
    };
    if (onSubmit) {
      onSubmit(formData);
    }
  }, [mode, audioFile, title, date, interviewer, companyName, contacts, dealStage, segment, transcript, detectedFormat, onSubmit, onCreated, onClose, audioLanguage]);

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
        if (typeof file.text === 'function') {
          file.text().then((text) => handleTranscriptChange(text));
        } else {
          const reader = new FileReader();
          reader.onload = () => handleTranscriptChange(reader.result as string);
          reader.readAsText(file);
        }
      }
    },
    [handleTranscriptChange],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        if (typeof file.text === 'function') {
          file.text().then((text) => handleTranscriptChange(text));
        } else {
          const reader = new FileReader();
          reader.onload = () => handleTranscriptChange(reader.result as string);
          reader.readAsText(file);
        }
      }
    },
    [handleTranscriptChange],
  );

  // Company combobox filter
  const filteredCompanies = companies?.filter(
    (c) => companyName && c.name.toLowerCase().includes(companyName.toLowerCase()),
  ) ?? [];
  const showCreateOption = companyName && !companies?.some(
    (c) => c.name.toLowerCase() === companyName.toLowerCase(),
  );

  const handleCompanySelect = (name: string) => {
    setCompanyName(name);
    setCompanyDropdownOpen(false);
  };

  const addContact = () => {
    setContacts((prev) => [...prev, { name: '', role: '' }]);
  };

  const updateContact = (index: number, field: 'name' | 'role', value: string) => {
    setContacts((prev) =>
      prev.map((c, i) => (i === index ? { ...c, [field]: value } : c)),
    );
  };

  const removeContact = (index: number) => {
    setContacts((prev) => prev.filter((_, i) => i !== index));
  };

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
          <label htmlFor="modal-title" className="text-xs font-semibold text-ink-2">Title</label>
          <input
            id="modal-title"
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            placeholder="Acme Watches — discovery call"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              setTitleManuallyEdited(true);
            }}
            required
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="modal-date" className="text-xs font-semibold text-ink-2">Date</label>
          <input
            id="modal-date"
            type="datetime-local"
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="modal-interviewer" className="text-xs font-semibold text-ink-2">Interviewer</label>
          <input
            id="modal-interviewer"
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            value={interviewer}
            onChange={(e) => setInterviewer(e.target.value)}
          />
        </div>

        {/* Company combobox */}
        <div className="flex flex-col gap-1 relative">
          <label htmlFor="modal-company" className="text-xs font-semibold text-ink-2">Company</label>
          <input
            id="modal-company"
            className="px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
            placeholder="Type to search or create…"
            value={companyName}
            onChange={(e) => {
              setCompanyName(e.target.value);
              setCompanyDropdownOpen(true);
            }}
            onFocus={() => setCompanyDropdownOpen(true)}
            onBlur={() => {
              // Delay to allow click on dropdown items
              setTimeout(() => setCompanyDropdownOpen(false), 200);
            }}
            role="combobox"
            aria-expanded={companyDropdownOpen}
            autoComplete="off"
          />
          {companyDropdownOpen && (filteredCompanies.length > 0 || showCreateOption) && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-surface border border-hairline rounded-lg shadow-lg z-10 max-h-40 overflow-auto">
              {filteredCompanies.map((c) => (
                <div
                  key={c.id}
                  className="px-2.5 py-1.5 text-sm hover:bg-page cursor-pointer"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => handleCompanySelect(c.name)}
                >
                  {c.name}
                </div>
              ))}
              {showCreateOption && (
                <div
                  className="px-2.5 py-1.5 text-sm text-accent hover:bg-page cursor-pointer border-t border-hairline"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => handleCompanySelect(companyName)}
                >
                  + Create "{companyName}"
                </div>
              )}
            </div>
          )}
        </div>

        {/* Contacts with roles */}
        <div className="flex flex-col gap-1">
          <label htmlFor="modal-contact-0" className="text-xs font-semibold text-ink-2">Contact(s)</label>
          {contacts.map((contact, idx) => (
            <div key={idx} className="flex gap-1.5 items-center">
              <input
                id={`modal-contact-${idx}`}
                className="flex-1 px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
                placeholder="Name"
                value={contact.name}
                onChange={(e) => updateContact(idx, 'name', e.target.value)}
                aria-label={idx === 0 ? 'Contact' : `Contact ${idx + 1}`}
              />
              <input
                className="flex-1 px-2.5 py-2 border border-hairline rounded-lg bg-page text-ink text-sm"
                placeholder="Role"
                value={contact.role}
                onChange={(e) => updateContact(idx, 'role', e.target.value)}
                aria-label={idx === 0 ? 'Role' : `Role ${idx + 1}`}
              />
              {contacts.length > 1 && (
                <button
                  type="button"
                  className="text-muted text-lg bg-transparent border-none cursor-pointer"
                  onClick={() => removeContact(idx)}
                  aria-label={`Remove contact ${idx + 1}`}
                >
                  ×
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="text-xs text-accent cursor-pointer bg-transparent border-none text-left mt-0.5"
            onClick={addContact}
          >
            + Add contact
          </button>
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="modal-deal-stage" className="text-xs font-semibold text-ink-2">Deal stage</label>
          <select
            id="modal-deal-stage"
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
          <label htmlFor="modal-segment" className="text-xs font-semibold text-ink-2">Plan / segment</label>
          <select
            id="modal-segment"
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
          <div className="flex items-center gap-3 mb-1">
            <label className="text-xs font-semibold text-ink-2">Input mode</label>
            <label className="flex items-center gap-1 text-xs cursor-pointer">
              <input
                type="radio"
                name="input-mode"
                value="text"
                checked={mode === 'text'}
                onChange={() => setMode('text')}
              />
              Paste / .txt / .vtt
            </label>
            <label className="flex items-center gap-1 text-xs cursor-pointer">
              <input
                type="radio"
                name="input-mode"
                value="audio"
                checked={mode === 'audio'}
                onChange={() => setMode('audio')}
              />
              Audio / Video upload
            </label>
          </div>

          {mode === 'text' && (
            <>
              <label htmlFor="modal-transcript" className="text-xs font-semibold text-ink-2">
                Transcript{' '}
                {detectedFormat && (
                  <span className="text-accent font-semibold">
                    · detected: {detectedFormat === 'vtt' ? 'VTT' : 'Name: text'}
                  </span>
                )}
              </label>
              <textarea
                id="modal-transcript"
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
            </>
          )}

          {mode === 'audio' && (
            <>
              <label htmlFor="audio-file-input" className="text-xs font-semibold text-ink-2">
                Audio / Video file
              </label>
              <div className="border-2 border-dashed border-hairline rounded-lg p-4 text-center">
                <input
                  id="audio-file-input"
                  type="file"
                  accept={AUDIO_EXTENSIONS.join(',')}
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) { setAudioFile(f); setAudioError(null); }
                  }}
                />
                {audioFile ? (
                  <div className="flex items-center justify-center gap-2">
                    <span className="text-sm font-medium text-ink">{audioFile.name}</span>
                    <span className="text-xs text-muted">({(audioFile.size / (1024 * 1024)).toFixed(1)} MB)</span>
                    <button
                      type="button"
                      className="text-xs text-red-600 hover:underline"
                      onClick={() => setAudioFile(null)}
                    >
                      Remove
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="text-sm text-accent hover:underline"
                    onClick={() => document.getElementById('audio-file-input')?.click()}
                  >
                    Choose file (.mp3, .mp4, .wav, .webm, .ogg, .m4a)
                  </button>
                )}
              </div>
              <div className="flex gap-2 items-center mt-1">
                <label htmlFor="audio-lang" className="text-xs text-muted">Language (optional):</label>
                <input
                  id="audio-lang"
                  className="px-2 py-1 border border-hairline rounded text-xs w-20"
                  placeholder="en"
                  value={audioLanguage}
                  onChange={(e) => setAudioLanguage(e.target.value)}
                />
              </div>
              {audioUploading && (
                <div className="flex items-center gap-2 mt-2 text-sm text-muted" role="status">
                  <span className="w-3 h-3 border-2 border-hairline border-t-accent rounded-full animate-spin" aria-hidden="true" />
                  Transcribing…
                </div>
              )}
              {audioError && (
                <p className="text-sm text-red-600 mt-1" role="alert">{audioError}</p>
              )}
            </>
          )}
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
          disabled={!title || (mode === 'text' && !transcript) || (mode === 'audio' && !audioFile) || isSubmitting || audioUploading}
          onClick={handleSubmit}
        >
          {audioUploading ? 'Transcribing…' : isSubmitting ? 'Creating…' : 'Create & analyze'}
        </button>
      </div>
    </dialog>
  );
}
