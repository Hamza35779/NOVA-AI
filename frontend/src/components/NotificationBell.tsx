import { useEffect, useState, useRef } from 'react';
import { Bell, Check } from 'lucide-react';
import { listNotifications, clearNotifications, getBase } from '../lib/api';
import { toast } from 'sonner';

export default function NotificationBell() {
  const [notifications, setNotifications] = useState<any[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchNotifications();

    const url = `${getBase()}/api/notifications/stream`;
    const eventSource = new EventSource(url);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setNotifications(prev => [data, ...prev]);
        toast(data.title || 'New Notification', {
          description: data.message,
          icon: data.urgency === 'high' ? '🔴' : data.urgency === 'normal' ? '🟡' : '⚪',
        });
      } catch (e) {}
    };

    return () => {
      eventSource.close();
    };
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [dropdownRef]);

  const fetchNotifications = async () => {
    try {
      const res = await listNotifications();
      setNotifications(res.notifications || []);
    } catch (e) {
      // ignore
    }
  };

  const handleClear = async () => {
    try {
      await clearNotifications();
      setNotifications([]);
    } catch (e) {
      toast.error('Failed to clear notifications');
    }
  };

  const unreadCount = notifications.length;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="relative p-2 rounded-full transition-colors"
        style={{ color: 'var(--color-text-secondary)' }}
        onMouseEnter={(e) => {
          e.currentTarget.style.color = 'var(--color-accent)';
          e.currentTarget.style.background = 'var(--color-bg-secondary)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.color = 'var(--color-text-secondary)';
          e.currentTarget.style.background = 'transparent';
        }}
        title="Notifications"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span
            className="absolute top-1 right-1 w-2.5 h-2.5 rounded-full"
            style={{ background: 'var(--color-error)', border: '2px solid var(--color-bg)' }}
          ></span>
        )}
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-80 rounded-xl shadow-xl z-50 overflow-hidden"
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <div
            className="flex justify-between items-center px-4 py-3"
            style={{ borderBottom: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
          >
            <h3 className="font-semibold" style={{ color: 'var(--color-text)' }}>Notifications</h3>
            {unreadCount > 0 && (
              <button
                onClick={handleClear}
                className="text-xs flex items-center gap-1 cursor-pointer transition-colors"
                style={{ color: 'var(--color-text-tertiary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-accent)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
              >
                <Check className="w-3 h-3" /> Mark all read
              </button>
            )}
          </div>

          <div className="max-h-96 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                No new notifications.
              </div>
            ) : (
              <div className="flex flex-col">
                {notifications.map((n, i) => (
                  <div
                    key={i}
                    className="px-4 py-3 transition-colors flex gap-3"
                    style={{ borderBottom: '1px solid var(--color-border-subtle)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                  >
                    <div className="mt-1 flex-shrink-0">
                      {n.urgency === 'high' ? (
                        <div className="w-2 h-2 rounded-full mt-1.5" style={{ background: 'var(--color-error)' }} />
                      ) : n.urgency === 'normal' ? (
                        <div className="w-2 h-2 rounded-full mt-1.5" style={{ background: 'var(--color-accent-amber)' }} />
                      ) : (
                        <div className="w-2 h-2 rounded-full mt-1.5" style={{ background: 'var(--color-text-tertiary)' }} />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>{n.title}</p>
                      <p className="text-xs mt-0.5 line-clamp-2" style={{ color: 'var(--color-text-secondary)' }}>{n.message}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
