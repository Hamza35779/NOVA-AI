import { useState, useEffect } from 'react';
import { Trash2, Pin } from 'lucide-react';
import { useNavigate } from 'react-router';
import { useAppStore } from '../../lib/store';
import { listHistory, updateConversation, deleteConversationAPI } from '../../lib/api';

interface Props {
  searchQuery: string;
}

function formatRelativeTime(timestamp: number): string {
  const diff = Date.now() - timestamp;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString();
}

export function ConversationList({ searchQuery }: Props) {
  const navigate = useNavigate();
  const localConversations = useAppStore((s) => s.conversations);
  const activeId = useAppStore((s) => s.activeId);
  const selectConversation = useAppStore((s) => s.selectConversation);
  const deleteLocalConversation = useAppStore((s) => s.deleteConversation);

  const [apiConversations, setApiConversations] = useState<any[]>([]);
  const [usingApi, setUsingApi] = useState(false);

  useEffect(() => {
    fetchApiHistory();
  }, [activeId]); // Refresh when active changes

  const fetchApiHistory = async () => {
    try {
      const res = await listHistory(50);
      setApiConversations(res.history || []);
      setUsingApi(true);
    } catch (e) {
      setUsingApi(false);
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (usingApi) {
      try {
        await deleteConversationAPI(id);
        fetchApiHistory();
      } catch (err) {
        console.error(err);
      }
    } else {
      deleteLocalConversation(id);
    }
  };

  const handlePin = async (id: string, currentPinned: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    if (usingApi) {
      try {
        await updateConversation(id, { pinned: !currentPinned });
        fetchApiHistory();
      } catch (err) {
        console.error(err);
      }
    }
  };

  const currentList = usingApi ? apiConversations : localConversations;

  const filtered = searchQuery
    ? currentList.filter((c) =>
        c.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : currentList;

  if (filtered.length === 0) {
    return (
      <div className="px-3 py-8 text-center text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        {searchQuery ? 'No matching chats' : 'No conversations yet'}
      </div>
    );
  }

  const pinned = filtered.filter(c => c.pinned);
  const unpinned = filtered.filter(c => !c.pinned);

  const renderList = (list: any[]) => (
    <div className="flex flex-col gap-0.5 py-1">
      {list.map((conv) => {
        const isActive = conv.id === activeId;
        const msgCount = conv.message_count || conv.messages?.length || 0;
        const updatedAt = conv.updated_at ? new Date(conv.updated_at).getTime() : (conv.updatedAt || Date.now());

        return (
          <div
            key={conv.id}
            className="group flex items-center rounded-lg cursor-pointer transition-colors"
            style={{
              background: isActive ? 'var(--color-bg-tertiary)' : 'transparent',
            }}
            onMouseEnter={(e) => {
              if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)';
            }}
            onMouseLeave={(e) => {
              if (!isActive) e.currentTarget.style.background = 'transparent';
            }}
          >
            <button
              onClick={() => {
                selectConversation(conv.id);
                navigate('/');
              }}
              className="flex-1 text-left px-3 py-2 min-w-0 cursor-pointer flex justify-between items-center"
            >
              <div className="min-w-0 flex-1">
                <div
                  className="text-sm truncate flex items-center gap-2"
                  style={{
                    color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                    fontWeight: isActive ? 500 : 400,
                  }}
                >
                  {conv.pinned && <Pin size={12} className="text-[#7C3AED] shrink-0 fill-[#7C3AED]" />}
                  <span className="truncate">{conv.title}</span>
                </div>
                <div className="text-[11px] mt-0.5 flex justify-between items-center" style={{ color: 'var(--color-text-tertiary)' }}>
                  <span>{formatRelativeTime(updatedAt)}</span>
                  {msgCount > 0 && (
                    <span className="bg-[#7C3AED]/20 text-[#7C3AED] px-1.5 rounded-full text-[10px]">
                      {msgCount}
                    </span>
                  )}
                </div>
              </div>
            </button>
            <div className="flex items-center opacity-0 group-hover:opacity-100 transition-opacity pr-1">
              {usingApi && (
                <button
                  onClick={(e) => handlePin(conv.id, conv.pinned, e)}
                  className="p-1.5 rounded transition-colors cursor-pointer"
                  style={{ color: 'var(--color-text-tertiary)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
                  title={conv.pinned ? "Unpin" : "Pin"}
                >
                  <Pin size={14} className={conv.pinned ? "fill-current" : ""} />
                </button>
              )}
              <button
                onClick={(e) => handleDelete(conv.id, e)}
                className="p-1.5 rounded cursor-pointer transition-colors"
                style={{ color: 'var(--color-text-tertiary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-error)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
                title="Delete conversation"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div>
      {pinned.length > 0 && (
        <div className="mb-2">
          <div className="px-3 text-xs font-semibold mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Pinned</div>
          {renderList(pinned)}
        </div>
      )}
      {unpinned.length > 0 && (
        <div>
          {pinned.length > 0 && <div className="px-3 text-xs font-semibold mb-1 mt-2" style={{ color: 'var(--color-text-tertiary)' }}>Recent</div>}
          {renderList(unpinned)}
        </div>
      )}
    </div>
  );
}
