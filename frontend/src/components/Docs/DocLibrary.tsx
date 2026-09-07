import React, { useState, useEffect } from 'react';
import { UploadCloud, FileText, Trash2, MessageSquare } from 'lucide-react';
import { listDocs, deleteDoc, uploadFiles } from '../../lib/api';

export function DocLibrary({ onChat }: { onChat: (docId: string | null) => void }) {
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const fetchDocs = async () => {
    try {
      const res = await listDocs();
      setDocs(res.documents || []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, []);

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;

    setLoading(true);
    try {
      await uploadFiles(files);
      await fetchDocs();
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;
    setLoading(true);
    try {
      await uploadFiles(files);
      await fetchDocs();
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteDoc(id);
      await fetchDocs();
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="flex flex-col h-full p-4" style={{ color: 'var(--color-text)' }}>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">Document Library</h2>
        <button
          onClick={() => onChat(null)}
          className="px-4 py-2 rounded-lg text-sm flex items-center gap-2 cursor-pointer transition-colors"
          style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)' }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-purple-hover)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent-purple)')}
        >
          <MessageSquare size={16} /> Chat with all
        </button>
      </div>

      <label
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        className="border-2 border-dashed rounded-xl p-8 flex flex-col items-center justify-center mb-6 transition cursor-pointer"
        style={{ borderColor: 'var(--color-accent-purple)', background: 'var(--color-accent-purple-subtle)' }}
      >
        <input type="file" multiple className="hidden" onChange={handleFileChange} />
        <UploadCloud size={48} className="mb-4" style={{ color: 'var(--color-accent)' }} />
        <p style={{ color: 'var(--color-text)' }}>Drag & drop files here or click to upload</p>
        <p className="text-sm mt-2" style={{ color: 'var(--color-text-tertiary)' }}>PDF, DOCX, TXT, MD, CSV</p>
        {loading && <p className="mt-4 animate-pulse" style={{ color: 'var(--color-accent-purple)' }}>Uploading...</p>}
      </label>

      <div className="flex-1 overflow-y-auto space-y-3">
        {docs.map(doc => (
          <div
            key={doc.id}
            className="p-4 rounded-xl flex items-center justify-between transition-all hover:-translate-y-0.5"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-sm)' }}
            onMouseEnter={(e) => (e.currentTarget.style.boxShadow = 'var(--shadow-md)')}
            onMouseLeave={(e) => (e.currentTarget.style.boxShadow = 'var(--shadow-sm)')}
          >
            <div className="flex items-center gap-3 overflow-hidden">
              <FileText className="shrink-0" size={24} style={{ color: 'var(--color-accent-purple)' }} />
              <div className="truncate">
                <p className="font-medium truncate">{doc.filename || doc.id}</p>
                <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{doc.chunk_count || 0} chunks</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => onChat(doc.id)}
                className="p-2 rounded-lg transition cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--color-bg-tertiary)';
                  e.currentTarget.style.color = 'var(--color-text)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.color = 'var(--color-text-secondary)';
                }}
                title="Chat with this doc"
              >
                <MessageSquare size={18} />
              </button>
              <button
                onClick={() => handleDelete(doc.id)}
                className="p-2 rounded-lg transition cursor-pointer"
                style={{ color: 'var(--color-text-tertiary)' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'color-mix(in srgb, var(--color-error) 15%, transparent)';
                  e.currentTarget.style.color = 'var(--color-error)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                  e.currentTarget.style.color = 'var(--color-text-tertiary)';
                }}
                title="Delete"
              >
                <Trash2 size={18} />
              </button>
            </div>
          </div>
        ))}
        {docs.length === 0 && !loading && (
          <div className="text-center mt-10" style={{ color: 'var(--color-text-tertiary)' }}>
            No documents uploaded yet.
          </div>
        )}
      </div>
    </div>
  );
}
