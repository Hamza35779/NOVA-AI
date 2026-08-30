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

  return (
    <div className="p-6 max-w-7xl mx-auto flex gap-6 h-full">
      {/* Main Column */}
      <div className="flex-1 flex flex-col gap-6">
        <div className="flex justify-between items-center">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white flex items-center gap-3">
            <Calendar className="w-8 h-8 text-indigo-600" />
            Calendar & Reminders
          </h1>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 text-sm">
              {status?.status === 'connected' ? (
                <span className="flex items-center gap-1 text-green-600 bg-green-50 px-3 py-1 rounded-full">
                  <CheckCircle className="w-4 h-4" /> Connected ({status.provider})
                </span>
              ) : (
                <span className="flex items-center gap-1 text-red-600 bg-red-50 px-3 py-1 rounded-full">
                  <AlertCircle className="w-4 h-4" /> Disconnected
                </span>
              )}
            </div>
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg hover:bg-indigo-700"
            >
              <Plus className="w-4 h-4" /> Schedule
            </button>
          </div>
        </div>

        {/* Morning Briefing Card */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-6 relative">
          <div className="flex justify-between items-start mb-4">
            <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center gap-2">
              <span className="text-2xl">🌅</span> Morning Briefing
            </h2>
            <button onClick={handleRefreshBriefing} className="p-2 text-gray-400 hover:text-indigo-600 rounded-full hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
              <RefreshCw className="w-5 h-5" />
            </button>
          </div>
          <p className="text-gray-700 dark:text-gray-300 leading-relaxed whitespace-pre-wrap">
            {briefing}
          </p>
        </div>

        {/* Today's Timeline */}
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-100 dark:border-gray-700 p-6 flex-1">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white mb-6">Upcoming Events</h2>
          
          {loading ? (
            <div className="animate-pulse flex flex-col gap-4">
              {[1, 2, 3].map(i => <div key={i} className="h-24 bg-gray-100 dark:bg-gray-700 rounded-lg"></div>)}
            </div>
          ) : events.length === 0 ? (
            <div className="text-center text-gray-500 py-12">No upcoming events found.</div>
          ) : (
            <div className="flex flex-col gap-4">
              {events.map((ev, i) => (
                <div key={i} className="flex flex-col sm:flex-row gap-4 p-4 rounded-lg border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 hover:border-indigo-200 transition-colors">
                  <div className="sm:w-48 flex flex-col justify-center border-b sm:border-b-0 sm:border-r border-gray-200 dark:border-gray-700 pb-4 sm:pb-0 sm:pr-4">
                    <div className="text-indigo-600 dark:text-indigo-400 font-semibold flex items-center gap-2 mb-1">
                      <Clock className="w-4 h-4" />
                      {new Date(ev.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                    <div className="text-sm text-gray-500">
                      {new Date(ev.start).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })}
                    </div>
                  </div>
                  
                  <div className="flex-1">
                    <h3 className="font-semibold text-lg text-gray-900 dark:text-white mb-2">{ev.summary}</h3>
                    <div className="flex flex-wrap gap-4 text-sm text-gray-600 dark:text-gray-400">
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
                      className="w-full sm:w-auto flex items-center justify-center gap-2 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 px-4 py-2 rounded-lg text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
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
        <div className="w-96 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-indigo-100 dark:border-indigo-900 p-6 flex flex-col h-[calc(100vh-8rem)] sticky top-6 overflow-y-auto">
          <div className="flex justify-between items-center mb-6 border-b border-gray-100 dark:border-gray-700 pb-4">
            <h2 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <FileText className="text-indigo-600 w-5 h-5" /> Prep
            </h2>
            <button onClick={() => setPrepPanel(null)} className="text-gray-400 hover:text-gray-600">&times;</button>
          </div>
          
          <h3 className="font-semibold text-indigo-600 mb-2 truncate">{prepPanel.event.summary}</h3>
          
          <div className="space-y-6">
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white mb-2 text-sm uppercase tracking-wider">Objectives</h4>
              <ul className="list-disc pl-5 space-y-1 text-gray-700 dark:text-gray-300 text-sm">
                {prepPanel.objectives?.map((obj: string, i: number) => <li key={i}>{obj}</li>) || <li>No specific objectives identified.</li>}
              </ul>
            </div>
            
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white mb-2 text-sm uppercase tracking-wider">Talking Points</h4>
              <ul className="list-disc pl-5 space-y-1 text-gray-700 dark:text-gray-300 text-sm">
                {prepPanel.talking_points?.map((tp: string, i: number) => <li key={i}>{tp}</li>) || <li>No talking points generated.</li>}
              </ul>
            </div>
            
            <div>
              <h4 className="font-semibold text-gray-900 dark:text-white mb-2 text-sm uppercase tracking-wider">Action Items</h4>
              <ul className="list-none space-y-2 text-sm">
                {prepPanel.action_items?.map((act: string, i: number) => (
                  <li key={i} className="flex gap-2 text-gray-700 dark:text-gray-300">
                    <input type="checkbox" className="mt-1 rounded text-indigo-600" />
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
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-md">
            <h2 className="text-xl font-bold mb-4 dark:text-white">Schedule Event</h2>
            <form onSubmit={handleCreateEvent} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Title</label>
                <input required type="text" className="w-full border rounded-lg p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value={newEvent.summary} onChange={e => setNewEvent({...newEvent, summary: e.target.value})} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Start</label>
                  <input required type="datetime-local" className="w-full border rounded-lg p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value={newEvent.start} onChange={e => setNewEvent({...newEvent, start: e.target.value})} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">End</label>
                  <input required type="datetime-local" className="w-full border rounded-lg p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value={newEvent.end} onChange={e => setNewEvent({...newEvent, end: e.target.value})} />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Location</label>
                <input type="text" className="w-full border rounded-lg p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value={newEvent.location} onChange={e => setNewEvent({...newEvent, location: e.target.value})} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                <textarea className="w-full border rounded-lg p-2 dark:bg-gray-700 dark:border-gray-600 dark:text-white" rows={3} value={newEvent.description} onChange={e => setNewEvent({...newEvent, description: e.target.value})} />
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button type="button" onClick={() => setShowModal(false)} className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg dark:text-gray-300 dark:hover:bg-gray-700">Cancel</button>
                <button type="submit" className="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700">Schedule</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
