/**
 * NOVA AI background service worker.
 * Registers context menus and handles messages from content scripts.
 */

const NOVA_BASE = 'http://localhost:8000';

// Register context menus on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'nova-ask',
    title: 'Ask NOVA AI',
    contexts: ['selection'],
  });
  chrome.contextMenus.create({
    id: 'nova-summarize',
    title: 'Summarize with NOVA AI',
    contexts: ['selection', 'page'],
  });
  chrome.contextMenus.create({
    id: 'nova-explain',
    title: 'Explain with NOVA AI',
    contexts: ['selection'],
  });
  chrome.contextMenus.create({
    id: 'nova-translate',
    title: 'Translate with NOVA AI',
    contexts: ['selection'],
  });
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const text = info.selectionText || '';
  const url = info.pageUrl || '';
  const actionMap = {
    'nova-ask': 'ask',
    'nova-summarize': 'summarize',
    'nova-explain': 'explain',
    'nova-translate': 'translate',
  };
  const action = actionMap[info.menuItemId] || 'ask';

  // Send to content script to open sidebar with pre-populated query
  if (tab?.id) {
    chrome.tabs.sendMessage(tab.id, {
      type: 'NOVA_CONTEXT_MENU',
      text,
      action,
      url,
    });
  }
});

// Handle keyboard shortcut
chrome.commands.onCommand.addListener((command, tab) => {
  if (command === 'toggle-nova-sidebar' && tab?.id) {
    chrome.tabs.sendMessage(tab.id, { type: 'NOVA_TOGGLE_SIDEBAR' });
  }
});

// Handle API calls from content script (bypass CORS)
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'NOVA_API_CALL') {
    const { endpoint, body } = msg;
    fetch(`${NOVA_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, data }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true; // keep channel open for async response
  }

  if (msg.type === 'NOVA_HEALTH_CHECK') {
    fetch(`${NOVA_BASE}/api/extension/health`)
      .then(r => r.json())
      .then(data => sendResponse({ ok: true, data }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
});
