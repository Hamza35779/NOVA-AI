const NOVA_BASE = 'http://localhost:8000';

const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const askBtn = document.getElementById('ask-btn');
const questionEl = document.getElementById('question');
const answerEl = document.getElementById('answer');
const openAppBtn = document.getElementById('open-app');

// Check if NOVA is running
async function checkHealth() {
  try {
    const res = await fetch(`${NOVA_BASE}/api/extension/health`, { signal: AbortSignal.timeout(2000) });
    if (res.ok) {
      statusDot.classList.add('online');
      statusText.textContent = 'NOVA AI running';
      askBtn.disabled = false;
    } else {
      throw new Error('not ok');
    }
  } catch {
    statusText.textContent = 'Not running — start with: nova serve';
    askBtn.disabled = true;
  }
}

askBtn.addEventListener('click', async () => {
  const q = questionEl.value.trim();
  if (!q) return;
  askBtn.textContent = 'Thinking...';
  askBtn.disabled = true;
  answerEl.style.display = 'none';
  try {
    const res = await fetch(`${NOVA_BASE}/api/extension/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: q, action: 'ask' }),
    });
    const data = await res.json();
    answerEl.textContent = data.answer || 'No response';
    answerEl.style.display = 'block';
  } catch {
    answerEl.textContent = 'NOVA AI is not reachable. Run: nova serve';
    answerEl.style.display = 'block';
  } finally {
    askBtn.textContent = 'Ask NOVA AI';
    askBtn.disabled = false;
  }
});

openAppBtn.addEventListener('click', () => {
  chrome.tabs.create({ url: NOVA_BASE });
});

questionEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    askBtn.click();
  }
});

checkHealth();
