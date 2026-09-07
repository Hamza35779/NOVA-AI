import React, { useState } from 'react';
import { DocLibrary } from '../components/Docs/DocLibrary';
import { DocChatPanel } from '../components/Docs/DocChatPanel';

export function DocsPage() {
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);

  return (
    <div className="flex h-full w-full">
      <div className="w-[40%] min-w-[300px]">
        <DocLibrary onChat={setSelectedDocId} />
      </div>
      <div className="flex-1 min-w-[400px]">
        <DocChatPanel selectedDocId={selectedDocId} />
      </div>
    </div>
  );
}
