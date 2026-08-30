/**
 * NOVA AI content script — injects a floating sidebar into any webpage.
 */

(function () {
  'use strict';

  let sidebar = null;
  let isVisible = false;

  function createSidebar() {
    if (sidebar) return;

    sidebar = document.createElement('div');
    sidebar.id = 'nova-ai-sidebar';
    sidebar.innerHTML = `
      <div class="nova-header">
        <div class="nova-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <circle cx="12" cy="12" r="10" stroke="#7C3AED" stroke-width="2"/>
            <path d="M8 12l3 3 5-5" stroke="#06B6D4" stroke-width="2" stroke-linecap="round"/>
          </svg>
          NOVA AI
        </div>
        <button id="nova-close" title="Close (Alt+N)">&times;</button>
      </div>
      <div class="nova-messages" id="nova-messages"></div>
      <div class="nova-actions">
        <button class="nova-action-btn" data-action="summarize">Summarize page</button>
        <button class="nova-action-btn" data-action="explain">Explain selection</button>
      </div>
      <div class="nova-input-row">
        <textarea id="nova-input" placeholder="Ask NOVA AI anything..." rows="2"></textarea>
        <button id="nova-send">&#9658;</button>
      </div>
    `;
    document.body.appendChild(sidebar);

    // Close button
    document.getElementById('nova-close').addEventListener('click', hideSidebar);

    // Send button
    document.getElementById('nova-send').addEventListener('click', () => {
      const text = document.getElementById('nova-input').value.trim();
      if (text) sendToNova(text, 'ask');
    });

    // Enter to send (Shift+Enter for newline)
    document.getElementById('nova-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const text = document.getElementById('nova-input').value.trim();
        if (text) sendToNova(text, 'ask');
      }
    });

    // Quick action buttons
    sidebar.querySelectorAll('.nova-action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const action = btn.dataset.action;
        const selection = window.getSelection()?.toString() || '';
        const text = action === 'summarize'
          ? `Summarize this page. Title: ${document.title}. URL: ${window.location.href}`
          : selection || 'No text selected';
        sendToNova(text, action);
      });
    });
  }

  function showSidebar(prefillText, action) {
    createSidebar();
    sidebar.classList.add('nova-visible');
    isVisible = true;
    if (prefillText) {
      document.getElementById('nova-input').value = prefillText;
    }
    if (action && prefillText) {
      sendToNova(prefillText, action);
    } else {
      document.getElementById('nova-input').focus();
    }
  }

  function hideSidebar() {
    if (sidebar) {
      sidebar.classList.remove('nova-visible');
      isVisible = false;
    }
  }

  function toggleSidebar() {
    isVisible ? hideSidebar() : showSidebar();
  }

  function addMessage(role, text) {
    const messages = document.getElementById('nova-messages');
    if (!messages) return;
    const div = document.createElement('div');
    div.className = `nova-msg nova-msg-${role}`;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function setLoading(loading) {
    const btn = document.getElementById('nova-send');
    if (btn) btn.textContent = loading ? '...' : '\u25B6';
    const input = document.getElementById('nova-input');
    if (input) input.disabled = loading;
  }

  function sendToNova(text, action) {
    addMessage('user', text);
    document.getElementById('nova-input').value = '';
    setLoading(true);

    chrome.runtime.sendMessage(
      {
        type: 'NOVA_API_CALL',
        endpoint: '/api/extension/ask',
        body: { text, action, context_url: window.location.href },
      },
      (response) => {
        setLoading(false);
        if (response?.ok) {
          addMessage('nova', response.data.answer || 'No response');
        } else {
          addMessage('nova', `NOVA AI is not running. Start it with: nova serve`);
        }
      }
    );
  }

  // Listen for messages from background script
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NOVA_TOGGLE_SIDEBAR') {
      toggleSidebar();
    } else if (msg.type === 'NOVA_CONTEXT_MENU') {
      showSidebar(msg.text, msg.action);
    }
  });
})();
