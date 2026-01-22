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
    const BUSINESS_ID = (window.RM_BUSINESS_ID || '').toString().trim();
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

    function openChat() {
        chatWidget.classList.add('open');
        chatLauncher.style.display = 'none';
        if (window.matchMedia('(min-width: 768px)').matches) {
            chatInput.focus();
        }
    }

    function closeChat() {
        chatWidget.classList.remove('open');
        chatLauncher.style.display = 'block';
    }

    function appendMessage(role, text, options = {}) {
        const bubble = document.createElement('div');
        bubble.className = `message ${role}`;
        if (options.html) {
            bubble.innerHTML = text;
        } else {
            bubble.textContent = text;
        }
        chatBody.appendChild(bubble);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    function showTyping(show) {
        typingIndicator.classList.toggle('hidden', !show);
    }

    function showToast(message) {
        if (!leadToast) return;
        leadToast.textContent = message;
        leadToast.classList.remove('hidden');
        setTimeout(() => leadToast.classList.add('hidden'), 2500);
    }

    function endChatSession() {
        chatEnded = true;
        chatInput.value = '';
        chatInput.disabled = true;
        sendButton.disabled = true;
        chatInputArea.style.display = 'none';
        chatInputArea.classList.add('hidden');
        chatInputArea.setAttribute('aria-hidden', 'true');
        ratingComponent.classList.remove('hidden');
    }

    function handleRating(e) {
        sessionRating = e.target.value;
        console.log('User rated:', sessionRating);
        ratingThankYou.classList.remove('hidden');
        // Optional: Disable further changes
        ratingInputs.forEach(input => input.disabled = true);
    }

    function updateProfilePanel(profile = {}, routing = {}) {
        latestProfile = profile || {};
        // Profile UI disabled for minimal widget; still keep latestProfile for lead form logic.
    }

    function handleRouting(routing, profile) {
        if (profile) {
            updateProfilePanel(profile, routing || {});
        }
        if (!routing) return;
        const shouldCard = routing.lead_capture === 'yes'
            || ((profile?.stage === 'contact' || profile?.stage === 'schedule') && !leadSubmitted);
        const contactOnFile = profile?.contact_email || profile?.contact_phone;
        const highIntent = routing.intent === 'book' || routing.intent === 'buy' || routing.intent === 'pricing';
        const hasProductOrDate = profile?.product_name || profile?.requested_date;
        if ((shouldCard || highIntent || hasProductOrDate) && !leadFormVisible && !leadSubmitted && !contactOnFile) {
            renderLeadForm(routing, false, profile || latestProfile);
        }
    }

    function renderLeadForm(routing = {}, force = false, profile = latestProfile) {
        if (leadFormVisible && !force) return;
        const existing = chatBody.querySelector('.lead-form');
        if (existing) existing.remove();

        const wrapper = document.createElement('form');
        wrapper.className = 'lead-form';

        const summaryText = routing.summary || profile.summary || 'To confirm availability we just need the best way to reach you.';
        pendingLeadMeta = {
            intent: routing.intent || profile.intent || 'other',
            summary: summaryText,
            urgency: routing.urgency || profile.urgency || 'unknown',
        };

        const emailOnFile = profile.contact_email || '';
        const phoneOnFile = profile.contact_phone || '';
        const defaultContact = phoneOnFile ? 'text' : 'email';

        const emailField = emailOnFile
            ? `<input type="hidden" name="email" value="${emailOnFile}"><p class="prefilled">Email on file: ${emailOnFile}</p>`
            : '<label>Email<input name="email" type="email" placeholder="email@example.com"></label>';
        const phoneField = phoneOnFile
            ? `<input type="hidden" name="phone" value="${phoneOnFile}"><p class="prefilled">Phone on file: ${phoneOnFile}</p>`
            : '<label>Phone<input name="phone" type="tel" placeholder="Optional but helpful"></label>';

        wrapper.innerHTML = `
            <strong>Concierge contact card</strong>
            <p class="lead-note">${summaryText}</p>
            <label>Full name<input name="name" placeholder="Your name" required></label>
            ${emailField}
            ${phoneField}
            <label>Preferred contact method
                <select name="contact_method">
                    <option value="email">Email</option>
                    <option value="text">Text</option>
                    <option value="call">Call</option>
                </select>
            </label>
            <label>Preferred time window<input name="preferred_time" placeholder="E.g., weekday evenings"></label>
            <div class="lead-form-actions">
                <button type="submit">Share details</button>
                <button type="button" class="lead-dismiss">Remind me later</button>
            </div>
        `;
        const contactSelect = wrapper.querySelector('select[name="contact_method"]');
        contactSelect.value = defaultContact;
        wrapper.addEventListener('submit', handleLeadSubmit);
        wrapper.querySelector('.lead-dismiss').addEventListener('click', () => {
            wrapper.remove();
            leadFormVisible = false;
        });
        chatBody.appendChild(wrapper);
        chatBody.scrollTop = chatBody.scrollHeight;
        leadFormVisible = true;
    }

    async function handleLeadSubmit(event) {
        event.preventDefault();
        if (!BUSINESS_ID) {
            appendMessage('assistant', 'Chat is not configured yet. Please set RM_BUSINESS_ID.');
            return;
        }
        const form = event.currentTarget;
        const formData = new FormData(form);
        const name = formData.get('name')?.toString().trim();
        const email = formData.get('email')?.toString().trim();
        const phone = formData.get('phone')?.toString().trim();
        const contactMethod = formData.get('contact_method')?.toString() || 'email';
        const preferredTime = formData.get('preferred_time')?.toString().trim() || '';

        if (!name) {
            alert('Please add your name.');
            return;
        }
        if (!email && !phone) {
            alert('Please add at least an email or phone number.');
            return;
        }

        const payload = {
            business_id: BUSINESS_ID,
            conversation_id: conversationId,
            name,
            email: email || '',
            phone: phone || '',
            contact_method: contactMethod,
            preferred_time: preferredTime,
            intent: pendingLeadMeta?.intent || 'other',
            urgency: pendingLeadMeta?.urgency || 'unknown',
            summary: pendingLeadMeta?.summary || 'Visitor needs follow up',
        };
        if (SHEETS_ID) payload.sheet_id = SHEETS_ID;

        try {
            const res = await fetch(`${API_BASE}/api/lead`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!res.ok) throw new Error('Lead submission failed');
            form.remove();
            leadFormVisible = false;
            leadSubmitted = true;
            pendingLeadMeta = null;
            appendMessage('assistant', 'Thank you — a stylist will reach out shortly. <a href="#contact" target="_blank">Book consultation</a>', { html: true });
            showToast('Lead captured ✅');
        } catch (err) {
            alert('Unable to submit lead yet. Make sure the backend is running.');
        }
    }

    async function sendMessage() {
        if (chatEnded) return;
        if (!BUSINESS_ID) {
            appendMessage('assistant', 'Chat is not configured yet. Please set RM_BUSINESS_ID.');
            return;
        }
        const message = chatInput.value.trim();
        if (!message) return;
        appendMessage('user', message);
        chatInput.value = '';
        showTyping(true);
        try {
            const response = await fetch(`${API_BASE}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    business_id: BUSINESS_ID,
                    conversation_id: conversationId,
                    message,
                    sheet_id: SHEETS_ID || undefined,
                }),
            });
            if (!response.ok) {
                throw new Error('Chat request failed');
            }
            const data = await response.json();
            saveConversation(data.conversation_id);
            appendMessage('assistant', data.reply);
            handleRouting(data.routing, data.profile);

            // Check for tool success logic
            if (data.lead_captured) {
                setTimeout(() => {
                    endChatSession();
                }, 800);
        }

    } catch (error) {
        appendMessage('assistant', 'The backend is unavailable right now. Sorry for the inconvenience!');
    } finally {
        showTyping(false);
    }
}

    function resetChat() {
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
