import React, { useEffect, useState, useRef } from 'react';
import { Bell, X, Check, AlertCircle } from 'lucide-react';
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
        className="relative p-2 text-gray-500 hover:text-indigo-600 rounded-full hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 transition-colors"
      >
        <Bell className="w-5 h-5" />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-white dark:border-gray-900"></span>
        )}
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 bg-white dark:bg-gray-800 rounded-xl shadow-xl border border-gray-100 dark:border-gray-700 z-50 overflow-hidden">
          <div className="flex justify-between items-center px-4 py-3 border-b border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50">
            <h3 className="font-semibold text-gray-900 dark:text-white">Notifications</h3>
            {unreadCount > 0 && (
              <button 
                onClick={handleClear}
                className="text-xs text-gray-500 hover:text-indigo-600 flex items-center gap-1"
              >
                <Check className="w-3 h-3" /> Mark all read
              </button>
            )}
          </div>
          
          <div className="max-h-96 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-500 dark:text-gray-400 text-sm">
                No new notifications.
              </div>
            ) : (
              <div className="flex flex-col">
                {notifications.map((n, i) => (
                  <div key={i} className="px-4 py-3 border-b border-gray-100 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors flex gap-3">
                    <div className="mt-1 flex-shrink-0">
                      {n.urgency === 'high' ? (
                        <div className="w-2 h-2 rounded-full bg-red-500 mt-1.5" />
                      ) : n.urgency === 'normal' ? (
                        <div className="w-2 h-2 rounded-full bg-yellow-500 mt-1.5" />
                      ) : (
                        <div className="w-2 h-2 rounded-full bg-gray-300 mt-1.5" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-white">{n.title}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">{n.message}</p>
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
