import React, { useState, useEffect } from 'react';
import { RefreshCw, Mail, CheckCircle, AlertCircle } from 'lucide-react';
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
    if (urgency === 'urgent') return 'var(--color-error)';
    if (urgency === 'normal') return 'var(--color-accent-amber)';
    return 'var(--color-text-tertiary)';
  };

  const inputStyle: React.CSSProperties = {
    width: '100%',
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    padding: '8px 10px',
    fontSize: 14,
    color: 'var(--color-text)',
  };

  return (
    <div className="flex h-full w-full" style={{ color: 'var(--color-text)' }}>
      {/* Column 1: Inbox */}
      <div className="w-[280px] flex flex-col" style={{ borderRight: '1px solid var(--color-border)' }}>
        <div className="p-4 flex justify-between items-center" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <h2 className="text-xl font-bold flex items-center gap-2"><Mail size={20} /> Inbox</h2>
          {configured && (
            <button
              onClick={fetchInbox}
              className="p-1 rounded transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto">
          {emails.map(email => (
            <div
              key={email.uid}
              onClick={() => { setSelectedEmail(email); setSummary(null); setDraft(null); }}
              className="p-3 cursor-pointer transition-colors"
              style={{
                borderBottom: '1px solid var(--color-border-subtle)',
                background: selectedEmail?.uid === email.uid ? 'var(--color-bg-secondary)' : 'transparent',
                borderLeft: selectedEmail?.uid === email.uid ? '4px solid var(--color-accent-purple)' : '4px solid transparent',
              }}
              onMouseEnter={(e) => {
                if (selectedEmail?.uid !== email.uid) e.currentTarget.style.background = 'var(--color-bg-secondary)';
              }}
              onMouseLeave={(e) => {
                if (selectedEmail?.uid !== email.uid) e.currentTarget.style.background = 'transparent';
              }}
            >
              <div className="flex justify-between items-start mb-1">
                <span className="font-medium text-sm truncate w-[180px]">{email.sender}</span>
                <AlertCircle size={14} style={{ color: urgencyColor(email.urgency || 'low') }} />
              </div>
              <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>{email.subject}</div>
            </div>
          ))}
          {!loading && emails.length === 0 && configured && (
            <div className="text-center p-4 text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No emails found</div>
          )}
        </div>
      </div>

      {/* Column 2: Email View */}
      <div className="flex-1 flex flex-col relative" style={{ borderRight: '1px solid var(--color-border)' }}>
        {selectedEmail ? (
          <>
            <div className="p-6" style={{ borderBottom: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}>
              <h1 className="text-2xl font-bold mb-2">{selectedEmail.subject}</h1>
              <div className="flex justify-between text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                <span>From: {selectedEmail.sender}</span>
                <span>{selectedEmail.date || 'Unknown date'}</span>
              </div>
              <div className="mt-4 flex gap-2">
                <button
                  onClick={handleSummary}
                  className="px-3 py-1 rounded text-sm transition cursor-pointer"
                  style={{ background: 'var(--color-accent-purple-subtle)', color: 'var(--color-accent-purple)' }}
                >
                  AI Summary
                </button>
                <button
                  onClick={handleDraft}
                  className="px-3 py-1 rounded text-sm transition cursor-pointer"
                  style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
                >
                  Draft Reply
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6 whitespace-pre-wrap" style={{ color: 'var(--color-text)' }}>
              {summary && (
                <div className="mb-6 p-4 rounded-xl" style={{ background: 'var(--color-accent-purple-subtle)', border: '1px solid var(--color-accent-purple)' }}>
                  <h3 className="font-bold mb-2 flex items-center gap-2" style={{ color: 'var(--color-accent-purple)' }}>
                    <CheckCircle size={16} /> AI Summary
                  </h3>
                  <p className="text-sm">{summary}</p>
                </div>
              )}
              {selectedEmail.body}
            </div>

            {draft !== null && (
              <div className="p-4" style={{ borderTop: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}>
                <div className="flex justify-between items-center mb-2">
                  <h3 className="font-bold" style={{ color: 'var(--color-accent)' }}>Draft Reply</h3>
                  <button
                    onClick={() => setDraft(null)}
                    className="text-sm transition-colors cursor-pointer"
                    style={{ color: 'var(--color-text-tertiary)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text)')}
                    onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
                  >Cancel</button>
                </div>
                <textarea
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  className="w-full h-32 rounded p-2 text-sm focus:outline-none"
                  style={{
                    background: 'var(--color-input-bg)',
                    border: '1px solid var(--color-input-border)',
                    color: 'var(--color-text)',
                  }}
                />
                <div className="flex justify-end mt-2">
                  <button
                    onClick={handleSend}
                    disabled={sending}
                    className="px-4 py-2 rounded font-medium disabled:opacity-50 cursor-pointer"
                    style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
                  >
                    {sending ? 'Sending...' : 'Send Reply'}
                  </button>
                </div>
              </div>
            )}
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
            Select an email to read
          </div>
        )}
      </div>

      {/* Column 3: Tools / Setup */}
      <div className="w-[300px] p-6 overflow-y-auto" style={{ background: 'var(--color-bg-secondary)' }}>
        {configured === false ? (
          <div>
            <h3 className="font-bold text-xl mb-4">Connect Email</h3>
            <form onSubmit={handleConnect} className="space-y-4">
              <div>
                <label className="block text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>IMAP Host</label>
                <input required value={imapHost} onChange={e => setImapHost(e.target.value)} style={inputStyle} placeholder="imap.gmail.com" />
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>Username</label>
                <input required value={username} onChange={e => setUsername(e.target.value)} style={inputStyle} placeholder="you@gmail.com" />
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>App Password</label>
                <input required type="password" value={password} onChange={e => setPassword(e.target.value)} style={inputStyle} />
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>SMTP Host</label>
                <input required value={smtpHost} onChange={e => setSmtpHost(e.target.value)} style={inputStyle} placeholder="smtp.gmail.com" />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="w-full p-2 rounded font-medium cursor-pointer"
                style={{ background: 'var(--color-accent-purple)', color: 'var(--color-on-accent)' }}
              >
                {loading ? 'Connecting...' : 'Connect'}
              </button>
            </form>
          </div>
        ) : (
          <div>
            <h3 className="font-bold text-xl mb-6">AI Triage</h3>
            <div className="space-y-4">
              <div className="p-4 rounded-xl flex items-center justify-between" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full" style={{ background: 'var(--color-error)' }}></div>
                  <span className="font-medium">Urgent</span>
                </div>
                <span className="text-xl font-bold">{emails.filter(e => e.urgency === 'urgent').length}</span>
              </div>
              <div className="p-4 rounded-xl flex items-center justify-between" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full" style={{ background: 'var(--color-accent-amber)' }}></div>
                  <span className="font-medium">Normal</span>
                </div>
                <span className="text-xl font-bold">{emails.filter(e => e.urgency === 'normal').length}</span>
              </div>
              <div className="p-4 rounded-xl flex items-center justify-between" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                <div className="flex items-center gap-3">
                  <div className="w-3 h-3 rounded-full" style={{ background: 'var(--color-text-tertiary)' }}></div>
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
