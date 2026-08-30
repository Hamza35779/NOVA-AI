import React, { useState } from 'react';
import { DocLibrary } from '../components/Docs/DocLibrary';
import { DocChatPanel } from '../components/Docs/DocChatPanel';

export function DocsPage() {
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  return (
    <div className="flex h-screen w-full bg-[#0F0B1E]">
      <div className="w-[40%] min-w-[300px] border-r border-white/10">
        <DocLibrary onChat={setSelectedDocId} />
      </div>
      <div className="flex-1 min-w-[400px]">
        <DocChatPanel selectedDocId={selectedDocId} />
      </div>
    </div>
  );
}
