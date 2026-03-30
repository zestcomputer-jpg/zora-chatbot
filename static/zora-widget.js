(function() {
  'use strict';

  // =========================================================================
  // ZORA Ai Agent — Embeddable Chat Widget for ZEST Mobile Shop
  // =========================================================================
  // Allow configuration via window.ZORA_SETTINGS before script loads
  const userSettings = window.ZORA_SETTINGS || {};

  // Auto-detect API base from script src if not configured
  function detectApiBase() {
    if (userSettings.apiBase) return userSettings.apiBase;
    const scripts = document.querySelectorAll('script[src*="widget.js"]');
    for (const s of scripts) {
      try {
        const url = new URL(s.src);
        return url.origin;
      } catch(e) {}
    }
    return 'https://zora-chatbot.onrender.com';
  }

  const ZORA_CONFIG = {
    apiBase: detectApiBase(),
    botName: 'ZORA Ai Agent',
    shopName: 'ZEST Mobile Shop',
    primaryColor: '#0066FF',
    accentColor: '#00C853',
    greeting: 'မင်္ဂလာပါ ခင်ဗျာ လူကြီးမင်း သိရှိလိုသည့် ဈေးနှုန်း ဖုန်း အမျိုးအစားများကို မေးမြန်းထားပေးပါ။\nZORA Ai Agent မှ ဖြေကြားပေးထားပါမယ်။\nမနက် (၈)နာရီမှ ည (၈)နာရီအတွင်း ကျွန်တော်တို့ ZEST MOBILE မှ CB တွင်ဝင်ရောက်စစ်ဆေးသည့် အချိန်၌သိရှိလိုသည်များကို ပြန်လည်ဖြေကြားပေးပါမယ်ခင်ဗျာ။  09 7978855 85 သို့ဆက်သွယ်မေးမြန်နိုင်ပါတယ်။\nhttps://zestmobileshop.com မှာလဲဝင်ရောက်ကြည့်ရှုနိုင်ပါတယ်။',
    quickActions: [
      { label: '📱 ဖုန်းဈေးနှုန်း',   message: 'ဖုန်းဈေးနှုန်း' },
      { label: '📋 ဈေးနှုန်းစာရင်း', message: 'ဈေးနှုန်းစာရင်း' },
      { label: '🔍 Specs ကြည့်မယ်',  message: 'specs ' },
      { label: '🔬 Research Tools',   message: 'research tools' },
      { label: '🏠 ဆိုင်တည်နေရာ',   message: 'ဆိုင်' },
      { label: '🛒 အော်ဒါမှာမယ်',   message: 'မှာမယ်' },
      { label: '🎬 Review ဗီဒီယို', message: 'review' },
      { label: '📞 ဆက်သွယ်ရန်',     message: 'ဆက်သွယ်' }
    ],
    greetingReply: 'ဘာများကူညီရမလဲ ခင်ဗျာ? 🌟\nအောက်ပါ ခလုတ်များကို နှိပ်ပြီး လိုအပ်သည်ကို ရွေးချယ်နိုင်ပါတယ်။'
  };

  // Session management
  let sessionId = localStorage.getItem('zora_session_id');
  if (!sessionId) {
    sessionId = 'web_' + Math.random().toString(36).substring(2, 14);
    localStorage.setItem('zora_session_id', sessionId);
  }

  let isOpen = false;
  let isLoading = false;
  let hasGreeted = false;

  // =========================================================================
  // Inject CSS
  // =========================================================================
  const style = document.createElement('style');
  style.textContent = `
    /* ZORA Widget Reset & Container */
    #zora-chat-widget * {
      margin: 0; padding: 0; box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Padauk', 'Myanmar Text', sans-serif;
    }

    /* Floating Button */
    #zora-chat-btn {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 64px;
      height: 64px;
      border-radius: 50%;
      background: linear-gradient(135deg, ${ZORA_CONFIG.primaryColor}, #0044CC);
      border: none;
      cursor: pointer;
      box-shadow: 0 4px 20px rgba(0,102,255,0.4);
      z-index: 99998;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.3s ease, box-shadow 0.3s ease;
      animation: zora-pulse 2s infinite;
    }
    #zora-chat-btn:hover {
      transform: scale(1.08);
      box-shadow: 0 6px 28px rgba(0,102,255,0.55);
    }
    #zora-chat-btn svg {
      width: 30px; height: 30px; fill: #fff;
      transition: transform 0.3s ease;
    }
    #zora-chat-btn.zora-open svg.zora-icon-chat { display: none; }
    #zora-chat-btn.zora-open svg.zora-icon-close { display: block; }
    #zora-chat-btn:not(.zora-open) svg.zora-icon-chat { display: block; }
    #zora-chat-btn:not(.zora-open) svg.zora-icon-close { display: none; }

    @keyframes zora-pulse {
      0%, 100% { box-shadow: 0 4px 20px rgba(0,102,255,0.4); }
      50% { box-shadow: 0 4px 30px rgba(0,102,255,0.65); }
    }

    /* Notification Badge */
    #zora-badge {
      position: absolute;
      top: -2px; right: -2px;
      width: 20px; height: 20px;
      background: #FF3B30;
      border-radius: 50%;
      border: 2px solid #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 11px;
      font-weight: 700;
      color: #fff;
    }
    #zora-badge.zora-hidden { display: none; }

    /* Chat Window */
    #zora-chat-window {
      position: fixed;
      bottom: 100px;
      right: 24px;
      width: 400px;
      max-width: calc(100vw - 32px);
      height: 580px;
      max-height: calc(100vh - 140px);
      background: #fff;
      border-radius: 20px;
      box-shadow: 0 12px 60px rgba(0,0,0,0.18);
      z-index: 99999;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      opacity: 0;
      transform: translateY(20px) scale(0.95);
      pointer-events: none;
      transition: opacity 0.3s ease, transform 0.3s ease;
    }
    #zora-chat-window.zora-visible {
      opacity: 1;
      transform: translateY(0) scale(1);
      pointer-events: auto;
    }

    /* Header */
    .zora-header {
      background: linear-gradient(135deg, ${ZORA_CONFIG.primaryColor}, #0044CC);
      color: #fff;
      padding: 18px 20px;
      display: flex;
      align-items: center;
      gap: 14px;
      flex-shrink: 0;
    }
    .zora-avatar {
      width: 44px; height: 44px;
      border-radius: 50%;
      background: rgba(255,255,255,0.2);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 22px;
      flex-shrink: 0;
    }
    .zora-header-info h3 {
      font-size: 16px;
      font-weight: 700;
      line-height: 1.2;
    }
    .zora-header-info p {
      font-size: 12px;
      opacity: 0.85;
      margin-top: 2px;
    }
    .zora-status-dot {
      display: inline-block;
      width: 8px; height: 8px;
      background: ${ZORA_CONFIG.accentColor};
      border-radius: 50%;
      margin-right: 5px;
      animation: zora-blink 1.5s infinite;
    }
    @keyframes zora-blink {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }

    /* Messages Area */
    .zora-messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      background: #F5F7FA;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .zora-messages::-webkit-scrollbar { width: 5px; }
    .zora-messages::-webkit-scrollbar-track { background: transparent; }
    .zora-messages::-webkit-scrollbar-thumb { background: #ccc; border-radius: 10px; }

    /* Message Bubbles */
    .zora-msg {
      max-width: 85%;
      padding: 12px 16px;
      border-radius: 18px;
      font-size: 14px;
      line-height: 1.6;
      word-wrap: break-word;
      white-space: pre-wrap;
      animation: zora-fadeIn 0.3s ease;
    }
    @keyframes zora-fadeIn {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .zora-msg-bot {
      background: #fff;
      color: #1a1a1a;
      align-self: flex-start;
      border-bottom-left-radius: 6px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .zora-msg-user {
      background: ${ZORA_CONFIG.primaryColor};
      color: #fff;
      align-self: flex-end;
      border-bottom-right-radius: 6px;
    }
    .zora-msg-bot a {
      color: ${ZORA_CONFIG.primaryColor};
      text-decoration: underline;
    }

    /* Typing Indicator */
    .zora-typing {
      display: flex;
      gap: 5px;
      padding: 12px 18px;
      background: #fff;
      border-radius: 18px;
      border-bottom-left-radius: 6px;
      align-self: flex-start;
      box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    }
    .zora-typing span {
      width: 8px; height: 8px;
      background: #aaa;
      border-radius: 50%;
      animation: zora-bounce 1.4s infinite ease-in-out;
    }
    .zora-typing span:nth-child(1) { animation-delay: -0.32s; }
    .zora-typing span:nth-child(2) { animation-delay: -0.16s; }
    @keyframes zora-bounce {
      0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
      40% { transform: scale(1); opacity: 1; }
    }

    /* Quick Actions */
    .zora-quick-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 4px 0;
      align-self: flex-start;
    }
    .zora-quick-btn {
      background: #fff;
      border: 1.5px solid ${ZORA_CONFIG.primaryColor};
      color: ${ZORA_CONFIG.primaryColor};
      padding: 8px 14px;
      border-radius: 20px;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.2s ease;
      white-space: nowrap;
    }
    .zora-quick-btn:hover {
      background: ${ZORA_CONFIG.primaryColor};
      color: #fff;
    }

    /* Input Area */
    .zora-input-area {
      padding: 14px 16px;
      background: #fff;
      border-top: 1px solid #E8ECF0;
      display: flex;
      gap: 10px;
      align-items: flex-end;
      flex-shrink: 0;
    }
    .zora-input-area textarea {
      flex: 1;
      border: 1.5px solid #E0E4E8;
      border-radius: 22px;
      padding: 10px 18px;
      font-size: 14px;
      resize: none;
      outline: none;
      max-height: 100px;
      min-height: 42px;
      line-height: 1.4;
      font-family: inherit;
      transition: border-color 0.2s;
      background: #F9FAFB;
    }
    .zora-input-area textarea:focus {
      border-color: ${ZORA_CONFIG.primaryColor};
      background: #fff;
    }
    .zora-input-area textarea::placeholder {
      color: #999;
    }
    .zora-send-btn {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      background: ${ZORA_CONFIG.primaryColor};
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: background 0.2s, transform 0.15s;
    }
    .zora-send-btn:hover { background: #0055DD; transform: scale(1.05); }
    .zora-send-btn:disabled { background: #B0BEC5; cursor: not-allowed; transform: none; }
    .zora-send-btn svg { width: 20px; height: 20px; fill: #fff; }

    /* Footer */
    .zora-footer {
      text-align: center;
      padding: 6px;
      background: #fff;
      font-size: 11px;
      color: #999;
      border-top: 1px solid #f0f0f0;
      flex-shrink: 0;
    }
    .zora-footer a { color: ${ZORA_CONFIG.primaryColor}; text-decoration: none; }

    /* Mobile Responsive */
    @media (max-width: 480px) {
      #zora-chat-window {
        bottom: 0; right: 0;
        width: 100vw;
        max-width: 100vw;
        height: 100vh;
        max-height: 100vh;
        border-radius: 0;
      }
      #zora-chat-btn {
        bottom: 16px; right: 16px;
        width: 56px; height: 56px;
      }
      #zora-chat-btn svg { width: 26px; height: 26px; }
    }
  `;
  document.head.appendChild(style);

  // =========================================================================
  // Build HTML
  // =========================================================================
  const widgetHTML = `
    <div id="zora-chat-widget">
      <!-- Floating Chat Button -->
      <button id="zora-chat-btn" aria-label="Open chat">
        <span id="zora-badge" class="zora-hidden">1</span>
        <svg class="zora-icon-chat" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/><path d="M7 9h2v2H7zm4 0h2v2h-2zm4 0h2v2h-2z"/></svg>
        <svg class="zora-icon-close" viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>

      <!-- Chat Window -->
      <div id="zora-chat-window">
        <!-- Header -->
        <div class="zora-header">
          <div class="zora-avatar">🤖</div>
          <div class="zora-header-info">
            <h3>${ZORA_CONFIG.botName}</h3>
            <p><span class="zora-status-dot"></span>${ZORA_CONFIG.shopName}</p>
          </div>
        </div>

        <!-- Messages -->
        <div class="zora-messages" id="zora-messages"></div>

        <!-- Input -->
        <div class="zora-input-area">
          <textarea id="zora-input" rows="1" placeholder="စာရိုက်ထည့်ပါ..." maxlength="500"></textarea>
          <button class="zora-send-btn" id="zora-send" aria-label="Send">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>

        <!-- Footer -->
        <div class="zora-footer">
          Powered by <a href="https://zestmobileshop.com" target="_blank">ZEST Mobile</a> &bull; #Zest_is_the_Best
        </div>
      </div>
    </div>
  `;

  const container = document.createElement('div');
  container.innerHTML = widgetHTML;
  document.body.appendChild(container);

  // =========================================================================
  // DOM References
  // =========================================================================
  const chatBtn = document.getElementById('zora-chat-btn');
  const chatWindow = document.getElementById('zora-chat-window');
  const messagesEl = document.getElementById('zora-messages');
  const inputEl = document.getElementById('zora-input');
  const sendBtn = document.getElementById('zora-send');
  const badge = document.getElementById('zora-badge');

  // =========================================================================
  // Helper Functions
  // =========================================================================
  function scrollToBottom() {
    setTimeout(() => {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }, 50);
  }

  function linkify(text) {
    // Convert URLs to clickable links
    return text.replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
    );
  }

  function addMessage(text, sender) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `zora-msg zora-msg-${sender}`;
    if (sender === 'bot') {
      msgDiv.innerHTML = linkify(text);
    } else {
      msgDiv.textContent = text;
    }
    messagesEl.appendChild(msgDiv);
    scrollToBottom();
  }

  function addQuickActions(actions) {
    const wrapper = document.createElement('div');
    wrapper.className = 'zora-quick-actions';
    actions.forEach(action => {
      const btn = document.createElement('button');
      btn.className = 'zora-quick-btn';
      btn.textContent = action.label;
      btn.addEventListener('click', () => {
        wrapper.remove();
        sendMessage(action.message);
      });
      wrapper.appendChild(btn);
    });
    messagesEl.appendChild(wrapper);
    scrollToBottom();
  }

  function showTyping() {
    const typing = document.createElement('div');
    typing.className = 'zora-typing';
    typing.id = 'zora-typing-indicator';
    typing.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(typing);
    scrollToBottom();
  }

  function hideTyping() {
    const typing = document.getElementById('zora-typing-indicator');
    if (typing) typing.remove();
  }

  // =========================================================================
  // API Communication
  // =========================================================================
  async function sendMessage(text) {
    if (isLoading || !text.trim()) return;

    addMessage(text, 'user');
    inputEl.value = '';
    inputEl.style.height = 'auto';
    isLoading = true;
    sendBtn.disabled = true;
    showTyping();

    try {
      const response = await fetch(`${ZORA_CONFIG.apiBase}/web-chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Session-ID': sessionId
        },
        body: JSON.stringify({
          message: text,
          session_id: sessionId
        })
      });

      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const data = await response.json();
      hideTyping();

      if (data.responses && data.responses.length > 0) {
        data.responses.forEach((resp, i) => {
          setTimeout(() => addMessage(resp, 'bot'), i * 300);
        });
      } else {
        addMessage('တောင်းပန်ပါတယ် ခင်ဗျာ၊ ပြဿနာ ဖြစ်နေပါတယ်။ ခဏစောင့်ပြီး ထပ်ကြိုးစားပေးပါ။ 🙏', 'bot');
      }

      // Show quick_replies from API if present (e.g. after greeting intent)
      if (data.quick_replies && data.quick_replies.quick_replies) {
        const qrs = data.quick_replies.quick_replies;
        const delay = (data.responses ? data.responses.length : 0) * 300 + 200;
        // Show the "ဘာများကူညီရမလဲ" text then the buttons
        setTimeout(() => {
          addMessage(data.quick_replies.text, 'bot');
          setTimeout(() => addQuickActions(qrs), 300);
        }, delay);
      } else if (data.intent === 'thanks') {
        setTimeout(() => addQuickActions(ZORA_CONFIG.quickActions), (data.responses ? data.responses.length : 0) * 300 + 200);
      }

    } catch (error) {
      hideTyping();
      console.error('ZORA Widget Error:', error);
      addMessage('ဆာဗာနှင့် ချိတ်ဆက်၍ မရပါ။ ခဏစောင့်ပြီး ထပ်ကြိုးစားပေးပါ။\n\n📞 09 797 8855 85 သို့ တိုက်ရိုက်ဆက်သွယ်နိုင်ပါတယ်။', 'bot');
    } finally {
      isLoading = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  // =========================================================================
  // Event Handlers
  // =========================================================================
  // Toggle chat window
  chatBtn.addEventListener('click', () => {
    isOpen = !isOpen;
    chatWindow.classList.toggle('zora-visible', isOpen);
    chatBtn.classList.toggle('zora-open', isOpen);
    badge.classList.add('zora-hidden');

    if (isOpen && !hasGreeted) {
      hasGreeted = true;
      // Show greeting then "ဘာများကူညီရမလဲ" + shortcut buttons
      setTimeout(() => {
        addMessage(ZORA_CONFIG.greeting, 'bot');
        setTimeout(() => {
          addMessage(ZORA_CONFIG.greetingReply, 'bot');
          setTimeout(() => addQuickActions(ZORA_CONFIG.quickActions), 300);
        }, 600);
      }, 300);
    }

    if (isOpen) {
      setTimeout(() => inputEl.focus(), 400);
    }
  });

  // Send on button click
  sendBtn.addEventListener('click', () => {
    sendMessage(inputEl.value.trim());
  });

  // Send on Enter (Shift+Enter for new line)
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(inputEl.value.trim());
    }
  });

  // Auto-resize textarea
  inputEl.addEventListener('input', () => {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 100) + 'px';
  });

  // Show notification badge after 5 seconds if chat not opened
  setTimeout(() => {
    if (!isOpen) {
      badge.classList.remove('zora-hidden');
    }
  }, 5000);

  // Close on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isOpen) {
      isOpen = false;
      chatWindow.classList.remove('zora-visible');
      chatBtn.classList.remove('zora-open');
    }
  });

})();
