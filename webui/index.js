import * as msgs from "./js/messages.js";
import { speech } from "./js/speech.js";

// --- Global State ---
let autoScroll = true;
let context = "";
let connectionStatus = false;
let lastLogVersion = 0;
let lastLogGuid = "";
let lastSpokenNo = 0;
let appInitialized = false;

// --- Global UI Element Variables ---
let leftPanel, rightPanel, container, chatInput, sendButton, chatHistory;
let inputSection, statusSection, chatsSection, tasksSection, progressBar, autoScrollSwitch, timeDate;
let sidebarOverlay, toggleSidebarButton;

// --- Utility and Helper Functions ---

function generateGUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function adjustTextareaHeight() {
    if (!chatInput) return;
    chatInput.style.height = 'auto';
    chatInput.style.height = `${chatInput.scrollHeight}px`;
}

function isMobile() {
    return window.innerWidth <= 768;
}

function toggleCssProperty(selector, property, value) {
    for (const sheet of document.styleSheets) {
        try {
            for (const rule of sheet.cssRules || sheet.rules) {
                if (rule.selectorText === selector) {
                    if (value === undefined) {
                        rule.style.removeProperty(property);
                    } else {
                        rule.style.setProperty(property, value);
                    }
                    return;
                }
            }
        } catch (e) {
            // Ignore CORS errors
        }
    }
}

// --- Toast Notifications ---

function hideToast() {
    const toastEl = document.getElementById('toast');
    if (!toastEl) return;
    if (toastEl.timeoutId) clearTimeout(toastEl.timeoutId);
    toastEl.classList.remove('show');
    setTimeout(() => { toastEl.style.display = 'none'; }, 400);
}

function toast(text, type = 'info', timeout = 5000) {
    const toastEl = document.getElementById('toast');
    if (!toastEl) return;
    if (toastEl.timeoutId) clearTimeout(toastEl.timeoutId);

    toastEl.querySelector('.toast__title').textContent = type.charAt(0).toUpperCase() + type.slice(1);
    toastEl.querySelector('.toast__message').textContent = text;
    toastEl.className = `toast toast--${type}`;
    
    const copyButton = toastEl.querySelector('.toast__copy');
    copyButton.style.display = type === 'error' ? 'inline-block' : 'none';
    copyButton.onclick = () => {
        navigator.clipboard.writeText(text);
        copyButton.textContent = 'Copied!';
        setTimeout(() => { copyButton.textContent = 'Copy'; }, 2000);
    };

    toastEl.querySelector('.toast__close').onclick = hideToast;
    
    toastEl.style.display = 'flex';
    setTimeout(() => toastEl.classList.add('show'), 10);

    if (timeout) {
        toastEl.timeoutId = setTimeout(hideToast, Math.max(timeout, 5000));
    }
}
window.toast = toast;


function toastFetchError(text, error) {
    const message = connectionStatus ? `${text}: ${error.message}` : `${text} (backend disconnected): ${error.message}`;
    toast(message, "error");
    console.error(text, error);
}
window.toastFetchError = toastFetchError;

// --- Backend Communication ---

async function sendJsonData(url, data) {
    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error(await response.text());
    return await response.json();
}
window.sendJsonData = sendJsonData;

// --- State Management ---

function setContext(id) {
    if (id === context) return;
    context = id;
    lastLogGuid = "";
    lastLogVersion = 0;
    lastSpokenNo = 0;
    if (chatHistory) chatHistory.innerHTML = "";

    if (chatsSection?.__x?.$data) chatsSection.__x.$data.selected = id;
    if (tasksSection?.__x?.$data) tasksSection.__x.$data.selected = id;
}
window.setContext = setContext;

function getContext() {
    return context;
}
window.getContext = getContext;

function setConnectionStatus(connected) {
    connectionStatus = connected;
    if (statusSection) {
        const statusIcon = statusSection.querySelector('.status-icon');
        if (statusIcon) {
            const connectedCircle = statusIcon.querySelector('.connected-circle');
            const disconnectedCircle = statusIcon.querySelector('.disconnected-circle');
            if (connectedCircle && disconnectedCircle) {
                connectedCircle.style.opacity = connected ? '1' : '0';
                disconnectedCircle.style.opacity = connected ? '0' : '1';
            }
        }
    }
}

// --- UI Interaction Functions ---

function toggleSidebar(show) {
    if (!leftPanel || !rightPanel || !sidebarOverlay) return;
    const showSidebar = typeof show === 'boolean' ? show : leftPanel.classList.contains('hidden');
    leftPanel.classList.toggle('hidden', !showSidebar);
    rightPanel.classList.toggle('expanded', !showSidebar);
    sidebarOverlay.classList.toggle('visible', showSidebar && isMobile());
}

function handleResize() {
    if (!leftPanel || !rightPanel || !sidebarOverlay) return;
    if (isMobile()) {
        leftPanel.classList.add('hidden');
        rightPanel.classList.remove('expanded');
        sidebarOverlay.classList.remove('visible');
    } else {
        leftPanel.classList.remove('hidden');
        rightPanel.classList.add('expanded');
        sidebarOverlay.classList.remove('visible');
    }
}

function updateAfterScroll() {
    if (!chatHistory) return;
    const tolerancePx = 50;
    const isAtBottom = (chatHistory.scrollHeight - chatHistory.scrollTop) <= (chatHistory.clientHeight + tolerancePx);
    if (autoScrollSwitch) {
        autoScrollSwitch.checked = isAtBottom;
        autoScroll = isAtBottom;
    }
}

function handleChatInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// --- Main Application Logic ---

async function poll() {
    try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const response = await sendJsonData("/poll", {
            log_from: lastLogVersion,
            context: context || null,
            timezone: timezone
        });

        if (!response) {
            setConnectionStatus(false);
            return false;
        }

        setConnectionStatus(true);

        if (!context && response.context) setContext(response.context);
        if (response.context !== context) return false;

        if (lastLogGuid !== response.log_guid) {
            if (chatHistory) chatHistory.innerHTML = "";
            lastLogVersion = 0;
            lastLogGuid = response.log_guid;
        }

        if (lastLogVersion !== response.log_version) {
            response.logs.forEach(log => {
                setMessage(log.id || log.no, log.type, log.heading, log.content, log.temp, log.kvps);
            });
            afterMessagesUpdate(response.logs);
            lastLogVersion = response.log_version;
            updateProgress(response.log_progress, response.log_progress_active);
            return true;
        }
    } catch (error) {
        console.error('Error in polling function:', error);
        setConnectionStatus(false);
    }
    return false;
}

async function startPolling() {
    const shortInterval = 25;
    const longInterval = 250;
    const shortIntervalPeriod = 100;
    let shortIntervalCount = 0;

    async function _doPoll() {
        try {
            const updated = await poll();
            if (updated) shortIntervalCount = shortIntervalPeriod;
            
            const nextInterval = shortIntervalCount > 0 ? shortInterval : longInterval;
            if(shortIntervalCount > 0) shortIntervalCount--;

            setTimeout(_doPoll, nextInterval);
        } catch (error) {
            console.error('Error in polling loop:', error);
            setTimeout(_doPoll, longInterval);
        }
    }
    _doPoll();
}

function afterMessagesUpdate(logs) {
    if (localStorage.getItem('speech') === 'true') {
        speakMessages(logs);
    }
}

function speakMessages(logs) {
    for (let i = logs.length - 1; i >= 0; i--) {
        const log = logs[i];
        if (log.type === "response" && log.no > lastSpokenNo) {
            lastSpokenNo = log.no;
            speech.speak(log.content);
            return;
        }
    }
}

function updateProgress(progress, active) {
    if (!progressBar) return;
    progress = progress || "";
    progressBar.classList.toggle("shiny-text", active);
    if (progressBar.innerHTML !== progress) {
        progressBar.innerHTML = progress;
    }
}

// --- Global Window Functions for UI interaction ---

function newChat() {
    try {
        setContext(generateGUID());
        updateAfterScroll();
    } catch (e) {
        toastFetchError("Error creating new chat", e);
    }
};
window.newChat = newChat;

async function sendMessage() {
    if (!chatInput || !inputSection) return;

    try {
        const message = chatInput.value.trim();
        const inputAD = Alpine.$data(inputSection);
        const attachments = inputAD.attachments;
        const hasAttachments = attachments && attachments.length > 0;

        if (message || hasAttachments) {
            const messageId = generateGUID();
            let response;

            if (hasAttachments) {
                const attachmentsWithUrls = attachments.map(att => ({ ...att, url: URL.createObjectURL(att.file) }));
                setMessage(messageId, 'user', '', message, false, { attachments: attachmentsWithUrls });

                const formData = new FormData();
                formData.append('text', message);
                formData.append('context', context);
                formData.append('message_id', messageId);
                attachments.forEach(att => formData.append('attachments', att.file));

                response = await fetch('/message_async', { method: 'POST', body: formData });
            } else {
                setMessage(messageId, 'user', '', message, false);
                const data = { text: message, context, message_id: messageId };
                response = await fetch('/message_async', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
            }

            const jsonResponse = await response.json();
            if (jsonResponse && jsonResponse.context) {
                setContext(jsonResponse.context);
            } else {
                toast("No response context returned.", "error");
            }

            chatInput.value = '';
            inputAD.attachments = [];
            inputAD.hasAttachments = false;
            adjustTextareaHeight();
        }
    } catch (e) {
        toastFetchError("Error sending message", e);
    }
}
window.sendMessage = sendMessage;

async function pauseAgent(paused) {
    try {
        await sendJsonData("/pause", { paused, context });
    } catch (e) {
        toastFetchError("Error pausing agent", e);
    }
}
window.pauseAgent = pauseAgent;

async function resetChat(ctxid = null) {
    try {
        await sendJsonData("/chat_reset", { "context": ctxid || context });
        if (!ctxid) updateAfterScroll();
    } catch (e) {
        toastFetchError("Error resetting chat", e);
    }
}
window.resetChat = resetChat;

async function killChat(id) {
    if (!id) return console.error("No chat ID provided for deletion");
    try {
        const chatsAD = Alpine.$data(chatsSection);
        if (context === id) {
            const alternateChat = chatsAD.contexts.find(ctx => ctx.id !== id);
            setContext(alternateChat ? alternateChat.id : generateGUID());
        }
        await sendJsonData("/chat_remove", { context: id });
        chatsAD.contexts = chatsAD.contexts.filter(ctx => ctx.id !== id);
        updateAfterScroll();
        toast("Chat deleted successfully", "success");
    } catch (e) {
        toastFetchError("Error deleting chat", e);
    }
}
window.killChat = killChat;

async function selectChat(id) {
    if (id === context) return;

    const activeTab = localStorage.getItem('activeTab') || 'chats';
    const tasksAD = Alpine.$data(tasksSection);
    const isTask = tasksAD?.tasks?.some(task => task.id === id);

    if (isTask && activeTab !== 'tasks') {
        return activateTab('tasks', id);
    }
    if (!isTask && activeTab !== 'chats') {
        return activateTab('chats', id);
    }

    setContext(id);
    localStorage.setItem(isTask ? 'lastSelectedTask' : 'lastSelectedChat', id);
    poll();
    updateAfterScroll();
}
window.selectChat = selectChat;

function toggleDarkMode(isDark) {
    document.body.classList.toggle('dark-mode', isDark);
    document.body.classList.toggle('light-mode', !isDark);
    localStorage.setItem('darkMode', isDark);
};
window.toggleDarkMode = toggleDarkMode;

function toggleAutoScroll(shouldAutoScroll) {
    autoScroll = shouldAutoScroll;
    localStorage.setItem('autoScroll', shouldAutoScroll);
    if (autoScrollSwitch) autoScrollSwitch.checked = shouldAutoScroll;
};
window.toggleAutoScroll = toggleAutoScroll;

window.toggleJson = (show) => toggleCssProperty('.msg-json', 'display', show ? 'block' : 'none');
window.toggleThoughts = (show) => toggleCssProperty('.msg-thoughts', 'display', show ? 'block' : 'none');
window.toggleUtils = (show) => toggleCssProperty('.message-util', 'display', show ? 'block' : 'none');

window.toggleSpeech = function (isOn) {
    localStorage.setItem('speech', isOn);
    if (!isOn) speech.stop();
};

window.nudge = async () => {
    try {
        await sendJsonData("/nudge", { ctxid: getContext() });
    } catch (e) {
        toastFetchError("Error nudging agent", e);
    }
}

window.restart = async () => {
    if (!connectionStatus) return toast("Backend disconnected, cannot restart.", "error");
    try {
        await sendJsonData("/restart", {});
    } catch (e) {
        toast("Restarting...", "info", 0);
        for (let i = 0; i < 240; i++) {
            try {
                await sendJsonData("/health", {});
                hideToast();
                await new Promise(r => setTimeout(r, 400));
                return toast("Restarted", "success", 5000);
            } catch (err) {
                await new Promise(r => setTimeout(r, 250));
            }
        }
        hideToast();
        await new Promise(r => setTimeout(r, 400));
        toast("Restart timed out or failed", "error", 5000);
    }
}

async function readJsonFiles() {
    return new Promise((resolve, reject) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.multiple = true;
        input.onchange = async () => {
            if (!input.files.length) return resolve([]);
            const readPromises = Array.from(input.files).map(file => 
                new Promise((res, rej) => {
                    const reader = new FileReader();
                    reader.onload = () => res(reader.result);
                    reader.onerror = rej;
                    reader.readAsText(file);
                })
            );
            try {
                resolve(await Promise.all(readPromises));
            } catch (error) {
                reject(error);
            }
        };
        input.click();
    });
}

window.loadChats = async () => {
    try {
        const fileContents = await readJsonFiles();
        const response = await sendJsonData("/chat_load", { chats: fileContents });
        if (response?.ctxids?.length) {
            setContext(response.ctxids[0]);
            toast("Chats loaded.", "success");
        } else {
            toast("No response or chats returned.", "error");
        }
    } catch (e) {
        toastFetchError("Error loading chats", e);
    }
}

window.saveChat = async () => {
    try {
        const response = await sendJsonData("/chat_export", { ctxid: context });
        if (response) {
            downloadFile(`${response.ctxid}.json`, response.content);
            toast("Chat file downloaded.", "success");
        } else {
            toast("No response returned.", "error");
        }
    } catch (e) {
        toastFetchError("Error saving chat", e);
    }
}

function downloadFile(filename, content) {
    const blob = new Blob([content], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
}

function setupTabs() {
    const chatsTab = document.getElementById('chats-tab');
    const tasksTab = document.getElementById('tasks-tab');
    if (chatsTab && tasksTab) {
        chatsTab.addEventListener('click', () => activateTab('chats'));
        tasksTab.addEventListener('click', () => activateTab('tasks'));
    } else {
        setTimeout(setupTabs, 100);
    }
}

function activateTab(tabName, contextId = null) {
    const chatsTab = document.getElementById('chats-tab');
    const tasksTab = document.getElementById('tasks-tab');
    const chatsSection = document.getElementById('chats-section');
    const tasksSection = document.getElementById('tasks-section');

    if (!chatsTab || !tasksTab || !chatsSection || !tasksSection) return;

    const previousTab = localStorage.getItem('activeTab');
    if (previousTab === 'chats') {
        localStorage.setItem('lastSelectedChat', context);
    } else if (previousTab === 'tasks') {
        localStorage.setItem('lastSelectedTask', context);
    }

    localStorage.setItem('activeTab', tabName);
    chatsTab.classList.toggle('active', tabName === 'chats');
    tasksTab.classList.toggle('active', tabName === 'tasks');
    chatsSection.style.display = tabName === 'chats' ? '' : 'none';
    tasksSection.style.display = tabName === 'tasks' ? 'flex' : 'none';
    if (tabName === 'tasks') {
        tasksSection.style.flexDirection = 'column';
    }

    const newContextId = contextId || localStorage.getItem(tabName === 'chats' ? 'lastSelectedChat' : 'lastSelectedTask');
    if (newContextId && newContextId !== context) {
        setContext(newContextId);
    }
    poll();
}

function initializeActiveTab() {
    if (!localStorage.getItem('lastSelectedChat')) localStorage.setItem('lastSelectedChat', '');
    if (!localStorage.getItem('lastSelectedTask')) localStorage.setItem('lastSelectedTask', '');
    const activeTab = localStorage.getItem('activeTab') || 'chats';
    activateTab(activeTab);
}

function openTaskDetail(taskId) {
    if (window.Alpine) {
        const settingsButton = document.getElementById('settings');
        if (settingsButton) {
            settingsButton.click();
            const modalEl = document.getElementById('settingsModal');
            if (!modalEl) return console.error('Settings modal element not found');
            const modalData = Alpine.$data(modalEl);
            setTimeout(() => {
                modalData.switchTab('scheduler');
                setTimeout(() => {
                    const schedulerComponent = document.querySelector('[x-data="schedulerSettings"]');
                    if (!schedulerComponent) return console.error('Scheduler component not found');
                    Alpine.$data(schedulerComponent).showTaskDetail(taskId);
                }, 50);
            }, 25);
        } else {
            console.error('Settings button not found');
        }
    } else {
        console.error('Alpine.js not loaded');
    }
}
window.openTaskDetail = openTaskDetail;

function handleFiles(files, inputAD) {
    Array.from(files).forEach(file => {
        const ext = file.name.split('.').pop().toLowerCase();
        const isImage = ['jpg', 'jpeg', 'png', 'bmp'].includes(ext);
        const attachment = { file, type: isImage ? 'image' : 'file', name: file.name, extension: ext };

        if (isImage) {
            const reader = new FileReader();
            reader.onload = e => {
                attachment.url = e.target.result;
                inputAD.attachments.push(attachment);
                inputAD.hasAttachments = true;
            };
            reader.readAsDataURL(file);
        } else {
            inputAD.attachments.push(attachment);
            inputAD.hasAttachments = true;
        }
    });
}

window.handleFileUpload = function(event) {
    handleFiles(event.target.files, Alpine.$data(inputSection));
}

window.loadKnowledge = async function () {
    try {
        const fileContents = await readJsonFiles();
        const response = await sendJsonData("/import_knowledge", { knowledge: fileContents });
        toast(response ? "Knowledge imported." : "No response returned.", response ? "success" : "error");
    } catch (e) {
        toastFetchError("Error importing knowledge", e);
    }
}

// --- App Initialization ---

function initializeApp() {
    if (appInitialized) return;
    appInitialized = true;

    console.log('🚀 Starting application initialization...');

    const selectors = {
        leftPanel: '#left-panel', rightPanel: '#right-panel', container: '.container',
        chatInput: '#chat-input', sendButton: '#send-button', chatHistory: '#chat-history',
        inputSection: '#input-section', statusSection: '#status-section', chatsSection: '#chats-section',
        tasksSection: '#tasks-section', progressBar: '#progress-bar', autoScrollSwitch: '#auto-scroll-switch',
        timeDate: '#time-date', sidebarOverlay: '#sidebar-overlay', toggleSidebarButton: '#toggle-sidebar',
    };

    Object.entries(selectors).forEach(([key, selector]) => {
        window[key] = document.querySelector(selector);
        if (!window[key]) console.warn(`Element "${key}" with selector "${selector}" not found.`);
    });

    setupEventListeners();
    setupTabs();
    initializeActiveTab();
    handleResize();

    toggleDarkMode(localStorage.getItem('darkMode') !== 'false');
    if (autoScrollSwitch) {
        const savedAutoScroll = localStorage.getItem('autoScroll') !== 'false';
        autoScrollSwitch.checked = savedAutoScroll;
        toggleAutoScroll(savedAutoScroll);
    }

    startPolling();
    console.log('✅ Application initialization complete.');
}

document.addEventListener('DOMContentLoaded', () => {
    // This is a good place for any setup that must happen after the initial DOM is parsed,
    // but before Alpine or other scripts might be ready.
});

document.addEventListener('alpine:initialized', () => {
    console.log('Alpine.js initialized. Running app initialization.');
    initializeApp();
});

// Fallback for cases where the script loads after Alpine is already initialized
if (window.Alpine && window.Alpine.version) {
    setTimeout(() => {
        if (!appInitialized) {
            console.log('Alpine.js was already initialized. Running app initialization.');
            initializeApp();
        }
    }, 0);
}
