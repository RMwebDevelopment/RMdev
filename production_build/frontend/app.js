(() => {
    const API_BASE = (() => {
        const configured = (window.RM_API_BASE || '').toString().trim().replace(/\/$/, '');
        if (configured) return configured;
        // Default to deployed backend if not provided
        const fallback = 'https://rmdev-gthj.onrender.com';
        const origin = window.location.origin;
        if (origin && origin.startsWith('http')) return origin;
        return fallback;
    })();
    const SHEETS_ID = (window.RM_SHEETS_ID || '').toString().trim();
    const chatWidget = document.getElementById('chatWidget');
    const chatLauncher = document.getElementById('chatLauncher');
    const chatBody = document.getElementById('chatBody');
    const chatInput = document.getElementById('chatInput');
    const sendButton = document.getElementById('sendButton');
    const typingIndicator = document.getElementById('typingIndicator');
    const closeButton = document.getElementById('closeChat');
    const resetButton = document.getElementById('resetChat');
    const heroBtn = document.getElementById('heroChatBtn');
    const navBtn = document.getElementById('openChatBtn');
    const specialistBtn = document.getElementById('specialistBtn');
    const leadToast = document.getElementById('leadToast');
    const ratingComponent = document.getElementById('ratingComponent');
    const chatInputArea = document.getElementById('chatInputArea');
    const ratingInputs = document.querySelectorAll('input[name="rating"]');
    const ratingThankYou = document.getElementById('ratingThankYou');
    if (!chatWidget || !chatLauncher || !chatBody || !chatInput || !sendButton) {
        console.warn('Chat widget markup not found on page; skipping init.');
        return;
    }
    
    // Create dynamic typing bubble
    let typingBubble = null;
    
    function createTypingBubble() {
        const div = document.createElement('div');
        div.className = 'typing-indicator hidden';
        div.innerHTML = `
            <div class="typing-dots">
                <div class="dot"></div><div class="dot"></div><div class="dot"></div>
            </div>
            <span class="typing-text">Thinking...</span>
        `;
        chatBody.appendChild(div);
        return div;
    }

    const makeConversationId = () => (
        window.crypto && window.crypto.randomUUID
            ? window.crypto.randomUUID()
            : `conv-${Math.random().toString(36).slice(2, 10)}`
    );

    let conversationId = makeConversationId();
    let leadFormVisible = false;
    let leadSubmitted = false;
    let pendingLeadMeta = null;
    let latestProfile = {};
    let sessionRating = null;
    let chatEnded = false;

    function saveConversation(id) {
        conversationId = id;
    }
    
    function renderSuggestions(chips = []) {
        const existing = chatBody.querySelector('.suggestion-chips');
        if (existing) existing.remove();
        
        if (!chips.length) return;

        const wrapper = document.createElement('div');
        wrapper.className = 'suggestion-chips';
        
        chips.forEach(text => {
            const btn = document.createElement('button');
            btn.className = 'chip';
            btn.textContent = text;
            btn.onclick = () => {
                chatInput.value = text;
                sendMessage();
                wrapper.remove();
            };
            wrapper.appendChild(btn);
        });
        
        chatBody.appendChild(wrapper);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    function openChat() {
        chatWidget.classList.add('open');
        chatLauncher.style.display = 'none';
        if (window.matchMedia('(min-width: 768px)').matches) {
            chatInput.focus();
        }
        // Initial Greeting Chips if empty
        if (chatBody.childElementCount <= 1) { // <= 1 in case typing bubble is there
             renderSuggestions(['Find a home', 'Sell my property', 'Speak to agent']);
        }
    }

    function closeChat() {
        chatWidget.classList.remove('open');
        chatLauncher.style.display = 'block';
    }

    function buildCarousel(images = []) {
        const wrapper = document.createElement('div');
        wrapper.className = 'image-carousel';
        images.slice(0, 5).forEach((img, idx) => {
            const figure = document.createElement('figure');
            const imageEl = document.createElement('img');
            imageEl.src = img.src;
            imageEl.alt = img.alt || `Listing image ${idx + 1}`;
            imageEl.loading = 'lazy';
            imageEl.referrerPolicy = 'no-referrer';
            imageEl.onerror = () => {
                imageEl.onerror = null;
                imageEl.src = 'https://placehold.co/320x240?text=Image+unavailable';
                imageEl.alt = 'Image unavailable';
            };
            figure.appendChild(imageEl);
            if (img.alt) {
                const cap = document.createElement('figcaption');
                cap.textContent = img.alt;
                figure.appendChild(cap);
            }
            wrapper.appendChild(figure);
        });
        return wrapper;
    }

    function renderAssistantMessage(text, options = {}) {
        const bubble = document.createElement('div');
        bubble.className = 'message assistant';
        const images = [];
        let cleaned = text || '';

        // 1. Parse Image Tags for Carousel (fallback or gallery)
        const imgTag = /<image([1-5])(?:\s+src="([^"]+)")?(?:\s+alt="([^"]*)")?\s*>(.*?)<\/image\1>/gis;
        cleaned = cleaned.replace(imgTag, (_match, _idx, srcAttr, altAttr, inner) => {
            const src = (srcAttr || inner || '').trim();
            const alt = (altAttr || inner || '').trim();
            if (src) images.push({ src, alt });
            return '';
        });

        // 2. Parse Listing Card Tags
        const cardTag = /<listing-card\s+([^>]+)><\/listing-card>/gis;
        cleaned = cleaned.replace(cardTag, (_match, attrString) => {
            const attrs = {};
            const regex = /(\w+)="([^"]*)"/g;
            let m;
            while ((m = regex.exec(attrString)) !== null) {
                attrs[m[1]] = m[2];
            }

            const card = document.createElement('a');
            card.className = 'listing-card';
            card.href = attrs.link || '#';
            card.target = '_blank';
            
            const priceFormatted = attrs.price ? (attrs.price.startsWith('$') ? attrs.price : `$${Number(attrs.price).toLocaleString()}`) : 'Contact for Price';
            
            card.innerHTML = `
                ${attrs.image ? `<img src="${attrs.image}" class="listing-card-img" alt="${attrs.address}" referrerpolicy="no-referrer" onerror="this.onerror=null;this.src='https://placehold.co/600x400?text=Home';this.style.opacity='0.5';">` : ''}
                <div class="listing-card-content">
                    <span class="listing-card-price">${priceFormatted}</span>
                    <span class="listing-card-address">${attrs.address || 'Address Unavailable'}</span>
                    <div class="listing-card-stats">
                        <span><strong>${attrs.beds || '?'}</strong> bds</span>
                        <span><strong>${attrs.baths || '?'}</strong> ba</span>
                        <span><strong>${attrs.sqft || '?'}</strong> sqft</span>
                    </div>
                </div>
            `;
            return card.outerHTML;
        });

        if (options.html) {
            bubble.innerHTML = cleaned.trim();
        } else {
            bubble.innerHTML = cleaned.trim().replace(/\n/g, '<br>');
        }
        // Removed buildCarousel(images) to avoid duplicates with cards
        return bubble;
    }

    function appendMessage(role, text, options = {}) {
        const bubble = role === 'assistant'
            ? renderAssistantMessage(text, options)
            : (() => {
                const b = document.createElement('div');
                b.className = `message ${role}`;
                if (options.html) {
                    b.innerHTML = text;
                } else {
                    b.textContent = text;
                }
                return b;
            })();

        chatBody.appendChild(bubble);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

        function getTypingFlavor(text) {
            const lower = (text || '').toLowerCase();
            
            if (/(see|show|find|search|look|list|house|home|property|sqft|beds|baths)/i.test(lower)) {
                const opts = ["Searching listings...", "Finding your match...", "Checking the market...", "Looking up homes..."];
                return opts[Math.floor(Math.random() * opts.length)];
            }
            if (/(book|schedule|tour|visit|appointment|time|calendar)/i.test(lower)) {
                const opts = ["Checking availability...", "Reviewing calendar...", "Finding a slot...", "Coordinating times..."];
                return opts[Math.floor(Math.random() * opts.length)];
            }
            if (/(email|call|text|phone|contact|name|reach)/i.test(lower)) {
                const opts = ["Updating profile...", "Saving details...", "Noting that down..."];
                return opts[Math.floor(Math.random() * opts.length)];
            }
            
            const opts = ["Thinking...", "Processing...", "Just a moment..."];
            return opts[Math.floor(Math.random() * opts.length)];
        }
    
        function showTyping(show, userText = '') {
            if (!typingBubble) {
                typingBubble = createTypingBubble();
            }
            
            // Remove suggestions when typing starts
            const chips = chatBody.querySelector('.suggestion-chips');
            if (show && chips) chips.remove();
    
            if (show) {
                const flavor = getTypingFlavor(userText);
                const textSpan = typingBubble.querySelector('.typing-text');
                if (textSpan) textSpan.textContent = flavor;
    
                chatBody.appendChild(typingBubble);
                typingBubble.classList.remove('hidden');
            } else {
                typingBubble.classList.add('hidden');
            }
            chatBody.scrollTop = chatBody.scrollHeight;
        }
    
        function showToast(message) {
            if (!leadToast) return;
            leadToast.textContent = message;
            leadToast.classList.remove('hidden');
            setTimeout(() => leadToast.classList.add('hidden'), 2500);
        }
        
        // ... (rest of functions) ...
    
            async function sendMessage() {
                if (chatEnded) return;
                const message = chatInput.value.trim();
                if (!message) return;
                appendMessage('user', message);
                chatInput.value = '';
                showTyping(true, message);
                try {
                    const response = await fetch(`${API_BASE}/api/chat`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            conversation_id: conversationId,
                            message,
                            sheet_id: SHEETS_ID || undefined,
                        }),
                    });
                    if (!response.ok) {
                        throw new Error('Chat request failed');
                    }
                    
                    const reader = response.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
        
                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop(); // Keep incomplete line
        
                        for (const line of lines) {
                            if (!line.trim()) continue;
                            try {
                                const event = JSON.parse(line);
                                if (event.type === 'status') {
                                    const textSpan = typingBubble?.querySelector('.typing-text');
                                    if (textSpan) textSpan.textContent = event.message;
                                } else if (event.type === 'result') {
                                    const data = event.data;
                                    saveConversation(data.conversation_id);
                                    appendMessage('assistant', data.reply);
                                    handleRouting(data.routing, data.profile);
                                    
                                    if (data.lead_captured) {
                                        setTimeout(() => {
                                            endChatSession();
                                        }, 800);
                                    }
                                } else if (event.type === 'error') {
                                    console.error('Stream error:', event.message);
                                }
                            } catch (e) {
                                console.warn('JSON parse error', e);
                            }
                        }
                    }
        
                } catch (error) {
                    appendMessage('assistant', 'The backend is unavailable right now. Sorry for the inconvenience!');
                } finally {
                    showTyping(false);
                }
            }    function resetChat() {
        chatBody.innerHTML = '';
        leadFormVisible = false;
        leadSubmitted = false;
        pendingLeadMeta = null;
        sessionRating = null;
        chatEnded = false;
        ratingComponent.classList.add('hidden');
        chatInputArea.classList.remove('hidden');
        chatInputArea.style.display = '';
        chatInputArea.removeAttribute('aria-hidden');
        chatInput.disabled = false;
        sendButton.disabled = false;
        ratingThankYou.classList.add('hidden');
        ratingInputs.forEach(input => {
            input.checked = false;
            input.disabled = false;
        });
        const newId = makeConversationId();
        saveConversation(newId);
        openChat();
    }

    chatLauncher.addEventListener('click', openChat);
    heroBtn?.addEventListener('click', openChat);
    navBtn?.addEventListener('click', openChat);
    closeButton.addEventListener('click', closeChat);
    sendButton.addEventListener('click', sendMessage);
    resetButton.addEventListener('click', resetChat);
    ratingInputs.forEach(input => input.addEventListener('change', handleRating));
    
    specialistBtn?.addEventListener('click', () => {
        openChat();
        renderLeadForm({
            intent: 'book',
            summary: 'To hold a consultation slot we just need your preferred contact.',
            urgency: 'soon',
        }, true);
    });
    chatInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });

    chatInput.addEventListener('input', () => {
        const wrapper = chatInputArea.querySelector('.input-wrapper');
        if (chatInput.value.trim().length > 0) {
            wrapper.classList.add('active');
        } else {
            wrapper.classList.remove('active');
        }
    });

    document.querySelectorAll('.faq-question').forEach((btn) => {
        btn.addEventListener('click', () => {
            btn.parentElement.classList.toggle('active');
        });
    });

})();
