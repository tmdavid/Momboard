import { useState } from 'react';

interface ShareCardDialogProps {
  highlightId: number;
  quote: string;
  onClose: () => void;
}

export function ShareCardDialog({ highlightId, quote: _quote, onClose }: ShareCardDialogProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [anonymize, setAnonymize] = useState(true);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const cardUrl = `/api/highlights/${highlightId}/card.png?theme=${theme}&anonymize=${anonymize ? '1' : '0'}`;

  const handlePreview = async () => {
    setLoading(true);
    try {
      const res = await fetch(cardUrl, { credentials: 'include' });
      if (!res.ok) throw new Error('Failed to generate card');
      const blob = await res.blob();
      setPreviewUrl(URL.createObjectURL(blob));
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    const res = await fetch(cardUrl, { credentials: 'include' });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `quote-${highlightId}.png`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopy = async () => {
    const res = await fetch(cardUrl, { credentials: 'include' });
    if (!res.ok) return;
    const blob = await res.blob();
    try {
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob }),
      ]);
    } catch {
      // Fallback: download instead
      handleDownload();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-lg shadow-xl p-6 max-w-lg w-full mx-4"
        onClick={(e) => e.stopPropagation()}
        data-testid="share-dialog"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-medium">Share Quote Card</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {/* Preview area */}
        <div className="bg-gray-100 rounded aspect-video flex items-center justify-center mb-4 overflow-hidden">
          {previewUrl ? (
            <img src={previewUrl} alt="Quote card preview" className="w-full h-full object-contain" />
          ) : (
            <p className="text-gray-400 text-sm">Click Preview to generate card</p>
          )}
        </div>

        {/* Options */}
        <div className="flex gap-4 mb-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Theme</label>
            <select
              value={theme}
              onChange={(e) => setTheme(e.target.value as 'light' | 'dark')}
              className="border rounded px-2 py-1 text-sm"
              data-testid="theme-select"
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Privacy</label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={anonymize}
                onChange={(e) => setAnonymize(e.target.checked)}
                data-testid="anonymize-checkbox"
              />
              Anonymize company
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          <button
            onClick={handlePreview}
            disabled={loading}
            className="px-4 py-2 bg-gray-100 rounded text-sm hover:bg-gray-200"
          >
            {loading ? 'Generating...' : 'Preview'}
          </button>
          <button
            onClick={handleDownload}
            className="px-4 py-2 bg-indigo-600 text-white rounded text-sm hover:bg-indigo-700"
            data-testid="download-btn"
          >
            ⬇ Download PNG
          </button>
          <button
            onClick={handleCopy}
            className="px-4 py-2 border rounded text-sm hover:bg-gray-50"
            data-testid="copy-btn"
          >
            📋 Copy
          </button>
        </div>
      </div>
    </div>
  );
}
