import React, { useState, useEffect } from 'react';
import { RefreshCw, Mail, CheckCircle, Clock, AlertCircle } from 'lucide-react';
import { getEmailStatus, connectEmail, getInbox, getEmailSummary, draftReply, sendReply } from '../lib/api';

export function EmailPage() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [emails, setEmails] = useState<any[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // Setup form
  const [imapHost, setImapHost] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [smtpHost, setSmtpHost] = useState('');

  const checkStatus = async () => {
    try {
      const res = await getEmailStatus();
      setConfigured(res.configured);
      if (res.configured) fetchInbox();
    } catch (e) {
      console.error(e);
      setConfigured(false);
    }
  };

  useEffect(() => {
    checkStatus();
  }, []);

  const fetchInbox = async () => {
    setLoading(true);
    try {
      const res = await getInbox(20);
      setEmails(res.emails || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await connectEmail({ imap_host: imapHost, username, password, smtp_host: smtpHost });
      await checkStatus();
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleSummary = async () => {
    if (!selectedEmail) return;
    try {
      const res = await getEmailSummary(selectedEmail.uid);
      setSummary(res.summary);
    } catch (e) {
      console.error(e);
    }
  };

  const handleDraft = async () => {
    if (!selectedEmail) return;
    try {
      const res = await draftReply(selectedEmail.subject, selectedEmail.body);
      setDraft(res.draft);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSend = async () => {
    if (!selectedEmail || !draft) return;
    setSending(true);
    try {
      await sendReply(selectedEmail.sender, 'Re: ' + selectedEmail.subject, draft, selectedEmail.message_id);
      setDraft(null);
      alert('Reply sent!');
    } catch (e) {
      console.error(e);
    } finally {
      setSending(false);
    }
  };

  const urgencyColor = (urgency: string) => {
    if (urgency === 'urgent') return 'text-red-500';
    if (urgency === 'normal') return 'text-yellow-500';
    return 'text-gray-400';
  };

  return (
    <div className="flex h-screen w-full bg-[#0F0B1E] text-white">
      {/* Column 1: Inbox */}
      <div className="w-[280px] border-r border-white/10 flex flex-col">
        <div className="p-4 border-b border-white/10 flex justify-between items-center">
          <h2 className="text-xl font-bold flex items-center gap-2"><Mail size={20} /> Inbox</h2>
          {configured && (
            <button onClick={fetchInbox} className="p-1 hover:bg-white/10 rounded">
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto">
          {emails.map(email => (
            <div 
              key={email.uid} 
              onClick={() => { setSelectedEmail(email); setSummary(null); setDraft(null); }}
              className={`p-3 border-b border-white/5 cursor-pointer hover:bg-white/5 ${selectedEmail?.uid === email.uid ? 'bg-[#1E1533] border-l-4 border-l-[#7C3AED]' : ''}`}
            >
              <div className="flex justify-between items-start mb-1">
                <span className="font-medium text-sm truncate w-[180px]">{email.sender}</span>
                <AlertCircle size={14} className={urgencyColor(email.urgency || 'low')} />
              </div>
              <div className="text-xs text-gray-400 truncate">{email.subject}</div>
            </div>
          ))}
          {!loading && emails.length === 0 && configured && (
            <div className="text-center p-4 text-gray-500 text-sm">No emails found</div>
          )}
        </div>
      </div>

      {/* Column 2: Email View */}
      <div className="flex-1 flex flex-col border-r border-white/10 relative">
        {selectedEmail ? (
          <>
            <div className="p-6 border-b border-white/10 bg-[#1E1533]">
              <h1 className="text-2xl font-bold mb-2">{selectedEmail.subject}</h1>
              <div className="flex justify-between text-sm text-gray-400">
                <span>From: {selectedEmail.sender}</span>
                <span>{selectedEmail.date || 'Unknown date'}</span>
              </div>
              <div className="mt-4 flex gap-2">
                <button onClick={handleSummary} className="bg-purple-600/30 hover:bg-purple-600/50 text-[#7C3AED] px-3 py-1 rounded text-sm transition">
                  AI Summary
                </button>
                <button onClick={handleDraft} className="bg-cyan-600/30 hover:bg-cyan-600/50 text-[#06B6D4] px-3 py-1 rounded text-sm transition">
                  Draft Reply
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6 text-gray-200 whitespace-pre-wrap">
              {summary && (
                <div className="mb-6 p-4 bg-[#7C3AED]/10 border border-[#7C3AED]/30 rounded-xl">
                  <h3 className="text-[#7C3AED] font-bold mb-2 flex items-center gap-2">
                    <CheckCircle size={16} /> AI Summary
                  </h3>
                  <p className="text-sm">{summary}</p>
                </div>
              )}
              {selectedEmail.body}
            </div>

            {draft !== null && (
              <div className="p-4 border-t border-white/10 bg-[#1E1533]">
                <div className="flex justify-between items-center mb-2">
                  <h3 className="font-bold text-[#06B6D4]">Draft Reply</h3>
                  <button onClick={() => setDraft(null)} className="text-gray-400 hover:text-white text-sm">Cancel</button>
                </div>
                <textarea 
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  className="w-full h-32 bg-black/30 border border-white/10 rounded p-2 text-sm text-white focus:outline-none focus:border-[#06B6D4]"
                />
                <div className="flex justify-end mt-2">
                  <button 
                    onClick={handleSend} 
                    disabled={sending}
                    className="bg-[#06B6D4] hover:bg-cyan-600 text-black px-4 py-2 rounded font-medium disabled:opacity-50"
                  >
                    {sending ? 'Sending...' : 'Send Reply'}
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            Select an email to read
          </div>
        )}
      </div>

      {/* Column 3: Tools / Setup */}
      <div className="w-[300px] bg-[#1E1533] p-6 overflow-y-auto">
        {configured === false ? (
          <div>
            <h3 className="font-bold text-xl mb-4">Connect Email</h3>
            <form onSubmit={handleConnect} className="space-y-4">
              <div>
                <label className="block text-xs text-gray-400 mb-1">IMAP Host</label>
                <input required value={imapHost} onChange={e => setImapHost(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded p-2 text-sm text-white" placeholder="imap.gmail.com" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">Username</label>
                <input required value={username} onChange={e => setUsername(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded p-2 text-sm text-white" placeholder="you@gmail.com" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">App Password</label>
                <input required type="password" value={password} onChange={e => setPassword(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded p-2 text-sm text-white" />
              </div>
              <div>
                <label className="block text-xs text-gray-400 mb-1">SMTP Host</label>
                <input required value={smtpHost} onChange={e => setSmtpHost(e.target.value)} className="w-full bg-black/40 border border-white/10 rounded p-2 text-sm text-white" placeholder="smtp.gmail.com" />
              </div>
              <button type="submit" disabled={loading} className="w-full bg-[#7C3AED] hover:bg-purple-600 text-white p-2 rounded font-medium">
                {loading ? 'Connecting...' : 'Connect'}
              </button>
            </form>
          </div>
        ) : (
          <div>
            <h3 className="font-bold text-xl mb-6">AI Triage</h3>
            <div className="space-y-4">
              <div className="bg-black/20 p-4 rounded-xl border border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full bg-red-500"></div>
                  <span className="font-medium">Urgent</span>
                </div>
                <span className="text-xl font-bold">{emails.filter(e => e.urgency === 'urgent').length}</span>
              </div>
              <div className="bg-black/20 p-4 rounded-xl border border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
                  <span className="font-medium">Normal</span>
                </div>
                <span className="text-xl font-bold">{emails.filter(e => e.urgency === 'normal').length}</span>
              </div>
              <div className="bg-black/20 p-4 rounded-xl border border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full bg-gray-500"></div>
                  <span className="font-medium">Low</span>
                </div>
                <span className="text-xl font-bold">{emails.filter(e => e.urgency === 'low').length}</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
