import React, { useEffect, useState } from 'react';
import { Calendar, Clock, MapPin, Users, FileText, CheckCircle, AlertCircle, Plus, RefreshCw } from 'lucide-react';
import { getCalendarStatus, getCalendarEvents, getAgendaBriefing, prepMeetingAPI, createCalendarEvent } from '../lib/api';
import { toast } from 'sonner';

export default function CalendarPage() {
  const [status, setStatus] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [briefing, setBriefing] = useState<string>('');
  const [loading, setLoading] = useState(true);

  const [showModal, setShowModal] = useState(false);
  const [newEvent, setNewEvent] = useState({ summary: '', start: '', end: '', description: '', location: '' });

  const [prepPanel, setPrepPanel] = useState<any>(null);
  const [preppingId, setPreppingId] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [statRes, evRes] = await Promise.all([
        getCalendarStatus().catch(() => ({ status: 'error' })),
        getCalendarEvents(7).catch(() => ({ events: [] })),
      ]);
      setStatus(statRes);
      setEvents(evRes.events || []);

      try {
        const briefRes = await getAgendaBriefing();
        setBriefing(briefRes.briefing || 'No briefing available.');
      } catch (e) {
        setBriefing('Could not load morning briefing.');
      }
    } catch (error) {
      toast.error('Failed to load calendar data');
    }
    setLoading(false);
  };

  const handleRefreshBriefing = async () => {
    try {
      setBriefing('Refreshing briefing...');
      const briefRes = await getAgendaBriefing();
      setBriefing(briefRes.briefing || 'No briefing available.');
      toast.success('Briefing updated');
    } catch (e) {
      toast.error('Failed to refresh briefing');
    }
  };

  const handleCreateEvent = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createCalendarEvent(newEvent);
      toast.success('Event scheduled!');
      setShowModal(false);
      setNewEvent({ summary: '', start: '', end: '', description: '', location: '' });
      loadData();
    } catch (error) {
      toast.error('Failed to create event');
    }
  };

  const handlePrepMeeting = async (event: any) => {
    setPreppingId(event.id);
    try {
      const res = await prepMeetingAPI(event.summary, event.description || '', event.attendees || []);
      setPrepPanel({ ...res, event });
      toast.success('Meeting prep ready');
    } catch (e) {
      toast.error('Failed to prepare meeting');
    }
    setPreppingId(null);
  };

  const cardStyle: React.CSSProperties = {
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
  };
  const inputStyle: React.CSSProperties = {
    width: '100%',
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    padding: '8px 10px',
    background: 'var(--color-bg)',
    color: 'var(--color-text)',
  };

  return (
    <div className="p-6 max-w-7xl mx-auto flex gap-6 h-full overflow-y-auto">
      {/* Main Column */}
      <div className="flex-1 flex flex-col gap-6">
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold flex items-center gap-3" style={{ color: 'var(--color-text)' }}>
            <Calendar className="w-8 h-8" style={{ color: 'var(--color-accent)' }} />
            Calendar & Reminders
          </h1>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm">
              {status?.status === 'connected' ? (
                <span
                  className="flex items-center gap-1 px-3 py-1 rounded-full"
                  style={{ color: 'var(--color-success)', background: 'color-mix(in srgb, var(--color-success) 10%, transparent)' }}
                >
                  <CheckCircle className="w-4 h-4" /> Connected ({status.provider})
                </span>
              ) : (
                <span
                  className="flex items-center gap-1 px-3 py-1 rounded-full"
                  style={{ color: 'var(--color-error)', background: 'color-mix(in srgb, var(--color-error) 10%, transparent)' }}
                >
                  <AlertCircle className="w-4 h-4" /> Disconnected
                </span>
              )}
            </div>
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 px-4 py-2 rounded-lg transition-colors cursor-pointer"
              style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-hover)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent)')}
            >
              <Plus className="w-4 h-4" /> Schedule
            </button>
          </div>
        </div>

        {/* Morning Briefing Card */}
        <div className="rounded-xl p-6 relative" style={cardStyle}>
          <div className="flex justify-between items-start mb-4">
            <h2 className="text-xl font-semibold flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
              <span className="text-2xl">🌅</span> Morning Briefing
            </h2>
            <button
              onClick={handleRefreshBriefing}
              className="p-2 rounded-full transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              onMouseEnter={(e) => {
                e.currentTarget.style.color = 'var(--color-accent)';
                e.currentTarget.style.background = 'var(--color-bg-secondary)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.color = 'var(--color-text-tertiary)';
                e.currentTarget.style.background = 'transparent';
              }}
            >
              <RefreshCw className="w-5 h-5" />
            </button>
          </div>
          <p className="leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>
            {briefing}
          </p>
        </div>

        {/* Today's Timeline */}
        <div className="rounded-xl p-6 flex-1" style={cardStyle}>
          <h2 className="text-xl font-semibold mb-6" style={{ color: 'var(--color-text)' }}>Upcoming Events</h2>

          {loading ? (
            <div className="animate-pulse flex flex-col gap-4">
              {[1, 2, 3].map(i => <div key={i} className="h-24 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}></div>)}
            </div>
          ) : events.length === 0 ? (
            <div className="text-center py-12" style={{ color: 'var(--color-text-tertiary)' }}>No upcoming events found.</div>
          ) : (
            <div className="flex flex-col gap-4">
              {events.map((ev, i) => (
                <div
                  key={i}
                  className="flex flex-col sm:flex-row gap-4 p-4 rounded-lg border transition-colors"
                  style={{ borderColor: 'var(--color-border-subtle)', background: 'var(--color-bg-secondary)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border-subtle)')}
                >
                  <div className="sm:w-48 flex flex-col justify-center border-b sm:border-b-0 sm:border-r pb-4 sm:pb-0 sm:pr-4" style={{ borderColor: 'var(--color-border)' }}>
                    <div className="font-semibold flex items-center gap-2 mb-1" style={{ color: 'var(--color-accent)' }}>
                      <Clock className="w-4 h-4" />
                      {new Date(ev.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                    <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                      {new Date(ev.start).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}
                    </div>
                  </div>

                  <div className="flex-1">
                    <h3 className="font-semibold text-lg mb-2" style={{ color: 'var(--color-text)' }}>{ev.summary}</h3>
                    <div className="flex flex-wrap gap-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                      {ev.location && (
                        <div className="flex items-center gap-1"><MapPin className="w-4 h-4" /> {ev.location}</div>
                      )}
                      {ev.attendees && ev.attendees.length > 0 && (
                        <div className="flex items-center gap-1"><Users className="w-4 h-4" /> {ev.attendees.length} attendees</div>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center sm:pl-4">
                    <button
                      onClick={() => handlePrepMeeting(ev)}
                      disabled={preppingId === ev.id}
                      className="w-full sm:w-auto flex items-center justify-center gap-2 px-4 py-2 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
                      style={{
                        background: 'var(--color-surface)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-accent)',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-subtle)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-surface)')}
                    >
                      {preppingId === ev.id ? <RefreshCw className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
                      Prep
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Side Panel: Meeting Prep */}
      {prepPanel && (
        <div className="w-96 rounded-xl p-6 flex flex-col h-fit max-h-[calc(100vh-4rem)] sticky top-6 overflow-y-auto" style={cardStyle}>
          <div className="flex justify-between items-center mb-6 pb-4" style={{ borderBottom: '1px solid var(--color-border)' }}>
            <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
              <FileText className="w-5 h-5" style={{ color: 'var(--color-accent)' }} /> Prep
            </h2>
            <button
              onClick={() => setPrepPanel(null)}
              className="text-lg transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-tertiary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
            >&times;</button>
          </div>

          <h3 className="font-semibold mb-2 truncate" style={{ color: 'var(--color-accent)' }}>{prepPanel.event.summary}</h3>

          <div className="space-y-6">
            <div>
              <h4 className="font-semibold mb-2 text-sm uppercase tracking-wider" style={{ color: 'var(--color-text)' }}>Objectives</h4>
              <ul className="list-disc pl-5 space-y-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {prepPanel.objectives?.map((obj: string, i: number) => <li key={i}>{obj}</li>) || <li>No specific objectives identified.</li>}
              </ul>
            </div>

            <div>
              <h4 className="font-semibold mb-2 text-sm uppercase tracking-wider" style={{ color: 'var(--color-text)' }}>Talking Points</h4>
              <ul className="list-disc pl-5 space-y-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {prepPanel.talking_points?.map((tp: string, i: number) => <li key={i}>{tp}</li>) || <li>No talking points generated.</li>}
              </ul>
            </div>

            <div>
              <h4 className="font-semibold mb-2 text-sm uppercase tracking-wider" style={{ color: 'var(--color-text)' }}>Action Items</h4>
              <ul className="list-none space-y-2 text-sm">
                {prepPanel.action_items?.map((act: string, i: number) => (
                  <li key={i} className="flex gap-2" style={{ color: 'var(--color-text-secondary)' }}>
                    <input type="checkbox" className="mt-1" style={{ accentColor: 'var(--color-accent)' }} />
                    <span>{act}</span>
                  </li>
                )) || <li>No action items yet.</li>}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Schedule Modal */}
      {showModal && (
        <div className="fixed inset-0 flex items-center justify-center z-50 p-4" style={{ background: 'rgba(0,0,0,0.5)' }}>
          <div className="rounded-xl p-6 w-full max-w-md" style={cardStyle}>
            <h2 className="text-xl font-bold mb-4" style={{ color: 'var(--color-text)' }}>Schedule Event</h2>
            <form onSubmit={handleCreateEvent} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Title</label>
                <input required type="text" style={inputStyle} value={newEvent.summary} onChange={e => setNewEvent({...newEvent, summary: e.target.value})} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Start</label>
                  <input required type="datetime-local" style={inputStyle} value={newEvent.start} onChange={e => setNewEvent({...newEvent, start: e.target.value})} />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>End</label>
                  <input required type="datetime-local" style={inputStyle} value={newEvent.end} onChange={e => setNewEvent({...newEvent, end: e.target.value})} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Location</label>
                <input type="text" style={inputStyle} value={newEvent.location} onChange={e => setNewEvent({...newEvent, location: e.target.value})} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Description</label>
                <textarea style={inputStyle} rows={3} value={newEvent.description} onChange={e => setNewEvent({...newEvent, description: e.target.value})} />
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 rounded-lg transition-colors cursor-pointer"
                  style={{ color: 'var(--color-text-secondary)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >Cancel</button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-lg transition-colors cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-hover)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-accent)')}
                >Schedule</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
