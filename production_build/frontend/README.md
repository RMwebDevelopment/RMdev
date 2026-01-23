# Frontend (drag-and-drop widget)

Static HTML/CSS/JS chat widget. No build step required.

## Usage
1. Upload all files in this folder to your static host (e.g., place them under `/widget/`).
2. Add the embed snippet to your existing page (adjust paths if you use a different folder):
   ```html
   <!-- Widget styles -->
   <link rel="stylesheet" href="widget/styles.css">

   <!-- Widget markup -->
   <div class="chat-widget rmwebdev-widget" id="chatWidget" aria-live="polite">
     <div class="chat-header">
       <h2 class="chat-title">How can I help?</h2>
       <div class="chat-actions">
         <button id="resetChat" title="Reset chat" class="icon-btn" style="display: none;">
           <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path></svg>
         </button>
         <button id="closeChat" aria-label="Close chat" class="icon-btn">
           <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
         </button>
         <button id="specialistBtn" style="display:none;"></button>
       </div>
     </div>
     <div class="chat-body" id="chatBody"></div>
     <div class="activity-log hidden" id="activityLog" aria-live="polite">
       <div class="activity-header">
         <h4>System Log</h4>
         <button class="toggle-log" onclick="this.parentElement.parentElement.classList.toggle('minimized')">_</button>
       </div>
       <ul id="activityList"></ul>
     </div>
     <div class="typing-indicator hidden" id="typingIndicator">
       <div class="dot"></div><div class="dot"></div><div class="dot"></div>
     </div>
     <div class="rating-component hidden" id="ratingComponent">
       <h3 class="rating-title">How did we do?</h3>
       <div class="rating-stars">
         <input type="radio" name="rating" id="r5" value="5"><label for="r5"></label>
         <input type="radio" name="rating" id="r4.5" value="4.5" class="half"><label for="r4.5" class="half"></label>
         <input type="radio" name="rating" id="r4" value="4"><label for="r4"></label>
         <input type="radio" name="rating" id="r3.5" value="3.5" class="half"><label for="r3.5" class="half"></label>
         <input type="radio" name="rating" id="r3" value="3"><label for="r3"></label>
         <input type="radio" name="rating" id="r2.5" value="2.5" class="half"><label for="r2.5" class="half"></label>
         <input type="radio" name="rating" id="r2" value="2"><label for="r2"></label>
         <input type="radio" name="rating" id="r1.5" value="1.5" class="half"><label for="r1.5" class="half"></label>
         <input type="radio" name="rating" id="r1" value="1"><label for="r1"></label>
         <input type="radio" name="rating" id="r0.5" value="0.5" class="half"><label for="r0.5" class="half"></label>
       </div>
       <div id="ratingThankYou" class="rating-thanks hidden">Thank you!</div>
     </div>
     <p class="chat-terms">By interacting with this, you agree to the <a href="widget/terms.html" target="_blank" rel="noopener">Terms and Agreements</a>.</p>
     <div class="chat-input-area" id="chatInputArea">
       <div class="input-wrapper">
         <textarea id="chatInput" placeholder="Message..." rows="1"></textarea>
         <button id="sendButton" aria-label="Send message">
           <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="19" x2="12" y2="5"></line><polyline points="5 12 12 5 19 12"></polyline></svg>
         </button>
       </div>
     </div>
     <div class="lead-toast hidden" id="leadToast">
       <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
       <span>Lead captured</span>
     </div>
   </div>
   <button class="chat-launcher rmwebdev-launcher" id="chatLauncher">Chat with us</button>

   <!-- Config and script -->
   <script>
     window.RM_API_BASE = 'https://rmdev-gthj.onrender.com'; // backend API base
     window.RM_BUSINESS_ID = 'default'; // use 'default' if single-tenant
     window.RM_SHEETS_ID = 'YOUR_GOOGLE_SHEET_ID_HERE'; // optional override; passes sheet_id to backend
   </script>
   <script defer src="widget/app.js"></script>
   ```
3. Host `widget/terms.html` as-is or edit to your policy.
4. If you load the widget on a page with its own styles, keep the assets in `widget/` and use the relative paths shown above to avoid CSS conflicts.

## Terms notice
- The chat UI includes a notice: “By interacting with this, you agree to the Terms and Agreements,” linking to `widget/terms.html`. Update that file with your policy as needed.

## CSS scoping
- Widget styles are namespaced under the `rmwebdev-widget` and `rmwebdev-launcher` classes to avoid clashing with host-site styles. Keep those classes on the root widget div and launcher button.

## Endpoints expected
- `POST /api/chat` (expects `message`, optional `sheet_id` and `conversation_id`)
- `POST /api/lead` (expects contact fields, optional `sheet_id` and `conversation_id`)
Set `window.RM_API_BASE` to the host where these endpoints live (e.g., your Render URL), `window.RM_BUSINESS_ID` to your tenant ID, and optionally `window.RM_SHEETS_ID` to force a specific Google Sheet for this widget instance.
