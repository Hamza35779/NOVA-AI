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
    <div className="flex flex-col h-full bg-[#0F0B1E] text-white p-4">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">Document Library</h2>
        <button 
          onClick={() => onChat(null)}
          className="bg-[#7C3AED] hover:bg-purple-600 px-4 py-2 rounded-lg text-sm flex items-center gap-2"
        >
          <MessageSquare size={16} /> Chat with all
        </button>
      </div>

      <label
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
        className="border-2 border-dashed border-purple-500/30 rounded-xl p-8 flex flex-col items-center justify-center mb-6 bg-[#1E1533] hover:bg-[#1E1533]/80 transition cursor-pointer"
      >
        <input type="file" multiple className="hidden" onChange={handleFileChange} />
        <UploadCloud size={48} className="text-[#06B6D4] mb-4" />
        <p className="text-gray-300">Drag & drop files here or click to upload</p>
        <p className="text-gray-500 text-sm mt-2">PDF, DOCX, TXT, MD, CSV</p>
        {loading && <p className="text-purple-400 mt-4 animate-pulse">Uploading...</p>}
      </label>

      <div className="flex-1 overflow-y-auto space-y-3">
        {docs.map(doc => (
          <div key={doc.id} className="bg-[#1E1533] p-4 rounded-xl flex items-center justify-between border border-white/5">
            <div className="flex items-center gap-3 overflow-hidden">
              <FileText className="text-[#7C3AED] shrink-0" size={24} />
              <div className="truncate">
                <p className="font-medium truncate">{doc.filename || doc.id}</p>
                <p className="text-xs text-gray-400">{doc.chunk_count || 0} chunks</p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button 
                onClick={() => onChat(doc.id)}
                className="p-2 hover:bg-white/10 rounded-lg text-gray-300 hover:text-white transition"
                title="Chat with this doc"
              >
                <MessageSquare size={18} />
              </button>
              <button 
                onClick={() => handleDelete(doc.id)}
                className="p-2 hover:bg-red-500/20 rounded-lg text-gray-400 hover:text-red-400 transition"
                title="Delete"
              >
                <Trash2 size={18} />
              </button>
            </div>
          </div>
        ))}
        {docs.length === 0 && !loading && (
          <div className="text-center text-gray-500 mt-10">
            No documents uploaded yet.
          </div>
        )}
      </div>
    </div>
  );
}
