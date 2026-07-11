// State
const state = {
    currentSession: null,
    sessions: [],
    pendingFiles: [],
    uploadedFiles: [],
    categories: new Set(),
    filesRefreshInterval: null,
    currentEventSource: null,  // 当前流式任务
    streamSessionId: null,     // 流式任务所属会话
    pendingPreviewInterval: null,  // 轮询待确认预览的定时器
    currentPendingPreviewId: null, // 当前已显示的待确认预览ID
    autoContinueTimer: null,       // 自动继续轮询定时器
    autoContinueConfirmed: false,  // 是否已确认（取消/继续/发送）
    isSubmitting: false,           // 是否正在提交（防重复点击）
    isReconnecting: false,         // 是否正在断点续传（跳过历史事件）
    // Streaming state
    stream: {
        thinkingBlock: null,
        assistantEl: null,
        currentToolId: null,
        currentToolName: null,
        currentToolBlock: null,
        toolNames: new Map(),
        seenToolIds: new Set(),
        terminalCommands: new Set(),
        lastThinkingContent: null,
        lastTextContent: null,
        processedUserInputIds: new Set(),  // 已处理的用户输入请求ID
    }
};

// 断开当前流式连接（后台任务继续运行）
function disconnectCurrentStream() {
    if (state.currentEventSource) {
        state.currentEventSource.close();
        state.currentEventSource = null;
    }
    // 不清除streamSessionId，保留以便断点续传
    setSendButtonMode('send');
}

// 更新上下文使用量圆环
function updateContextRing(contextInfo) {
    const ring = $('#context-ring');
    if (!ring) return;
    
    const percent = contextInfo?.usage_percent || 0;
    const tokens = contextInfo?.estimated_tokens || 0;
    const maxTokens = contextInfo?.max_tokens || 120000;
    
    // 更新进度圆环 (stroke-dasharray: progress 100)
    const progress = ring.querySelector('.ring-progress');
    if (progress) {
        progress.setAttribute('stroke-dasharray', `${percent} 100`);
    }
    
    // 更新文本
    const text = ring.querySelector('.ring-text');
    if (text) {
        text.textContent = `${Math.round(percent)}%`;
    }
    
    // 更新颜色状态
    ring.classList.remove('warning', 'danger');
    if (percent >= 80) {
        ring.classList.add('danger');
    } else if (percent >= 60) {
        ring.classList.add('warning');
    }
    
    // 更新 tooltip
    ring.title = `上下文: ${(tokens/1000).toFixed(1)}K / ${(maxTokens/1000).toFixed(0)}K tokens (${percent.toFixed(1)}%)`;
}

// DOM Elements
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Init
document.addEventListener('DOMContentLoaded', () => {
    if (Api.token && Api.user) {
        showApp();
    } else {
        showAuth();
    }
    bindEvents();
});

// Auth
function showAuth() {
    $('#auth-page').classList.remove('hidden');
    $('#app-page').classList.add('hidden');
}

function showApp() {
    $('#auth-page').classList.add('hidden');
    $('#app-page').classList.remove('hidden');
    $('#username-display').textContent = Api.user.username;
    // 只有管理员显示管理后台按钮
    const adminBtn = $('#admin-btn');
    if (adminBtn) {
        adminBtn.style.display = Api.user.is_admin ? 'block' : 'none';
    }
    loadSessions();
    startFilesRefresh();
}

function bindEvents() {
    // Auth tabs
    $$('#auth-page .tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('#auth-page .tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            $('#login-form').classList.toggle('hidden', tab !== 'login');
            $('#register-form').classList.toggle('hidden', tab !== 'register');
        });
    });
    
    // Right sidebar tabs
    $$('.sidebar-right .tabs .tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.sidebar-right .tabs .tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            $$('.sidebar-right .tab-content').forEach(c => c.classList.remove('active'));
            $(`#tab-${tab}`).classList.add('active');
        });
    });

    // Login
    $('#login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = $('#login-username').value.trim();
        const password = $('#login-password').value;
        try {
            await Api.login(username, password);
            showApp();
        } catch (err) {
            $('#login-error').textContent = err.message;
        }
    });

    // Register
    $('#register-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = $('#register-username').value.trim();
        const password = $('#register-password').value;
        const confirm = $('#register-confirm').value;
        if (password !== confirm) {
            $('#register-error').textContent = '密码不一致';
            return;
        }
        try {
            await Api.register(username, password);
            await Api.login(username, password);
            showApp();
        } catch (err) {
            $('#register-error').textContent = err.message;
        }
    });

    // User menu
    $('#user-btn').addEventListener('click', () => {
        $('#user-dropdown').classList.toggle('hidden');
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.user-menu')) {
            $('#user-dropdown').classList.add('hidden');
        }
    });

    $('#logout-btn').addEventListener('click', () => {
        Api.clearAuth();
        stopFilesRefresh();
        showAuth();
    });

    // 管理后台页面
    $('#admin-btn').addEventListener('click', () => {
        $('#user-dropdown').classList.add('hidden');
        showAdminPage();
    });
    
    $('#back-to-app-btn').addEventListener('click', () => {
        showAppPage();
    });
    
    // 管理后台标签页切换
    $$('.admin-tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            // 切换按钮状态
            $$('.admin-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            // 切换内容
            $$('.admin-tab-content').forEach(c => c.classList.remove('active'));
            $(`#admin-tab-${tab}`).classList.add('active');
            // 加载对应内容
            if (tab === 'knowledge') {
                loadKnowledgeList();
            } else if (tab === 'prompt') {
                loadSystemPrompt();
            } else if (tab === 'sandbox') {
                loadSandboxData();
            }
        });
    });
    
    // 系统提示词编辑器
    initPromptEditor();
    
    // 沙箱管理初始化
    initSandboxManagement();
    
    // 管理后台搜索
    $('#knowledge-search-btn').addEventListener('click', () => loadKnowledgeList());
    $('#knowledge-search').addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadKnowledgeList();
    });

    $$('.close-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const modal = btn.closest('.modal-overlay') || btn.closest('.knowledge-modal-overlay');
            if (modal) modal.classList.add('hidden');
        });
    });

    $('#add-knowledge-btn').addEventListener('click', () => openKnowledgeEditModal());
    $('#cancel-knowledge-btn').addEventListener('click', () => {
        $('#knowledge-edit-modal').classList.add('hidden');
    });
    
    // 知识编辑弹窗关闭按钮
    $('#knowledge-edit-modal .close-btn').addEventListener('click', () => {
        $('#knowledge-edit-modal').classList.add('hidden');
    });

    $('#knowledge-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        await saveKnowledge();
    });

    $('#category-filter').addEventListener('change', () => loadKnowledgeList());
    
    // 初始化知识编辑器标签页
    initKnowledgeEditorTabs();

    // Chat
    $('#new-chat-btn').addEventListener('click', createNewSession);
    $('#refresh-files-btn').addEventListener('click', refreshSandboxFiles);
    
    // 下载ZIP按钮
    $('#download-zip-btn').addEventListener('click', downloadWorkspaceZip);
    
    // Toggle left sidebar
    $('#toggle-sidebar-btn').addEventListener('click', () => {
        $('.sidebar-left').classList.toggle('collapsed');
    });

    // File input
    $('#file-input').addEventListener('change', handleFileSelect);

    // Message input
    const msgInput = $('#message-input');
    msgInput.addEventListener('input', () => {
        msgInput.style.height = 'auto';
        msgInput.style.height = Math.min(msgInput.scrollHeight, 150) + 'px';
        // 用户输入时重置自动继续倒计时
        resetAutoContinueTimer();
    });

    msgInput.addEventListener('focus', () => {
        // 用户聚焦输入框时重置自动继续倒计时
        resetAutoContinueTimer();
    });

    msgInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // 粘贴文件支持
    msgInput.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        
        const files = [];
        for (const item of items) {
            if (item.kind === 'file') {
                const file = item.getAsFile();
                if (file) files.push(file);
            }
        }
        
        if (files.length > 0) {
            state.pendingFiles.push(...files);
            updateFilePreview();
        }
    });

    $('#send-btn').addEventListener('click', handleSendButtonClick);
}

// 发送按钮模式切换
function setSendButtonMode(mode) {
    const btn = $('#send-btn');
    if (!btn) return;
    
    if (mode === 'pause') {
        btn.textContent = '⏸';
        btn.title = '暂停并输入';
        btn.classList.add('pause-mode');
        btn.classList.remove('loading-mode');
        btn.disabled = false;
    } else if (mode === 'loading') {
        btn.textContent = '⏳';
        btn.title = '处理中...';
        btn.classList.add('loading-mode');
        btn.classList.remove('pause-mode');
        btn.disabled = true;
    } else {
        btn.textContent = '→';
        btn.title = '发送';
        btn.classList.remove('pause-mode', 'loading-mode');
        btn.disabled = false;
    }
}

// 处理发送按钮点击
async function handleSendButtonClick() {
    const btn = $('#send-btn');
    if (btn.classList.contains('pause-mode')) {
        // 暂停模式：触发用户中断输入
        await triggerUserInterrupt();
    } else {
        // 发送模式：发送消息
        sendMessage();
    }
}

// 触发用户中断输入
async function triggerUserInterrupt() {
    if (!state.currentSession) return;
    
    // 立即停止所有轮询，避免在中断信号设置前触发 /pending API
    stopPendingPreviewPolling();
    stopAutoContinuePolling();
    hideAutoContinueBar(true);
    
    // 调用后端中断 API
    try {
        await fetch(`/api/conversation/session/${state.currentSession}/interrupt`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
        });
    } catch (err) {
        console.error('Interrupt agent error:', err);
    }
}

// Sessions
async function loadSessions() {
    try {
        state.sessions = await Api.listSessions();
        renderSessions();
        if (state.sessions.length > 0 && !state.currentSession) {
            selectSession(state.sessions[0].session_id);
        }
    } catch (err) {
        console.error('Load sessions error:', err);
    }
}

function renderSessions() {
    const container = $('#sessions-list');
    if (state.sessions.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无对话</div>';
        return;
    }
    container.innerHTML = state.sessions.map(s => {
        const name = formatSessionName(s);
        return `
        <div class="list-item ${s.session_id === state.currentSession ? 'active' : ''}" 
             data-id="${s.session_id}">
            <span class="title" title="${escapeHtml(name)}">${escapeHtml(name)}</span>
            <button class="delete-btn" data-id="${s.session_id}" title="删除">×</button>
        </div>
    `}).join('');

    container.querySelectorAll('.list-item').forEach(item => {
        item.addEventListener('click', (e) => {
            if (!e.target.classList.contains('delete-btn')) {
                selectSession(item.dataset.id);
            }
        });
    });

    container.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (confirm('确定删除此对话？')) {
                await Api.deleteSession(btn.dataset.id);
                if (state.currentSession === btn.dataset.id) {
                    state.currentSession = null;
                    $('#messages').innerHTML = '';
                }
                loadSessions();
            }
        });
    });
}

function formatSessionName(session) {
    // 优先使用会话名称（用户第一条消息）
    if (session.name) {
        // 截取前30个字符
        const name = session.name.length > 30 ? session.name.substring(0, 30) + '...' : session.name;
        return name;
    }
    // 没有名称则使用日期
    const date = new Date(session.created_at);
    return `对话 ${date.toLocaleDateString()} ${date.toLocaleTimeString().slice(0, 5)}`;
}

async function selectSession(sessionId) {
    // 断开当前流式连接（后台任务继续运行）
    disconnectCurrentStream();
    
    // 切换会话时隐藏自动继续条
    hideAutoContinueBar(true);
    
    // 停止旧会话的预览轮询，清理预览状态
    stopPendingPreviewPolling();
    state.currentPendingPreviewId = null;
    
    // 移除当前显示的所有预览卡片（属于旧会话）
    document.querySelectorAll('.plan-preview-card, .kuncode-preview-card, .user-input-request-card').forEach(card => {
        if (card.dataset.countdownTimer) {
            clearInterval(parseInt(card.dataset.countdownTimer));
        }
        card.remove();
    });
    
    state.currentSession = sessionId;
    renderSessions();
    
    // 重置流式状态
    state.stream = {
        thinkingBlock: null,
        assistantEl: null,
        currentToolId: null,
        currentToolName: null,
        currentToolBlock: null,
        toolNames: new Map(),
        seenToolIds: new Set(),
        terminalCommands: new Set(),
        lastThinkingContent: null,
        lastHistoryTextContent: null,  // 用于断点续传时跳过已显示的文本
        processedUserInputIds: new Set(),  // 已处理的用户输入请求ID
    };
    
    // 清空右侧面板状态（计划、文件、终端）
    clearRightPanelState();
    
    try {
        // 加载历史消息
        const detail = await Api.getSession(sessionId);
        renderMessages(detail.messages);
        updateContextRing(detail.context_info);
        refreshSandboxFiles();
        
        // 加载计划（从历史状态恢复）
        loadPlan();
        
        // 检查是否有待确认的预览（断点续传时恢复倒计时）
        loadPendingPreview();
        
        // 检查是否有正在执行的任务（断点续传）
        const taskInfo = await Api.getSessionTask(sessionId);
        if (taskInfo.has_active_task && taskInfo.task_id) {
            // console.log('断点续传: 重新连接任务', taskInfo.task_id);
            reconnectToTask(taskInfo.task_id);
        }
    } catch (err) {
        console.error('Load session error:', err);
    }
}

// 加载待确认的预览（断点续传时恢复倒计时）
async function loadPendingPreview() {
    if (!state.currentSession) return;
    
    // 保存当前会话ID，用于后续检查会话是否变化
    const currentSessionAtStart = state.currentSession;
    
    try {
        const resp = await fetch(`/api/kuncode/${currentSessionAtStart}/pending`, {
            headers: { 'Authorization': `Bearer ${Api.token}` }
        });
        
        if (!resp.ok) return;
        
        const data = await resp.json();
        // console.log('loadPendingPreview:', data);
        
        if (!data.has_pending) {
            // 检查页面上是否有预览卡片（包括超时后仍显示的卡片）
            const existingCards = document.querySelectorAll('.plan-preview-card, .kuncode-preview-card, .user-input-request-card');
            const hadPendingPreview = state.currentPendingPreviewId != null || existingCards.length > 0;
            
            // 移除所有超时的预览卡片
            existingCards.forEach(card => {
                if (card.dataset.countdownTimer) {
                    clearInterval(parseInt(card.dataset.countdownTimer));
                }
                card.remove();
            });
            
            state.currentPendingPreviewId = null;
            hideAutoContinueBar();
            
            // 如果之前有预览卡片，说明可能是超时自动执行了，检查是否有运行中的任务
            if (hadPendingPreview && !state.currentEventSource && state.currentSession === currentSessionAtStart) {
                try {
                    const taskInfo = await Api.getSessionTask(currentSessionAtStart);
                    if (taskInfo.has_active_task && taskInfo.task_id && state.currentSession === currentSessionAtStart) {
                        console.log('预览超时，自动重连任务:', taskInfo.task_id);
                        reconnectToTask(taskInfo.task_id);
                    }
                } catch (err) {
                    console.error('检查运行中任务失败:', err);
                }
            }
            return;
        }
        
        // auto_continue 类型的 preview_id 直接在 data 上
        const previewId = data.preview_id || (data.preview && data.preview.preview_id);
        const remainingSeconds = data.remaining_seconds || 0;
        
        // auto_triggered 类型：后端已自动触发继续，前端需要显示消息并重连
        if (data.preview_type === 'auto_triggered') {
            hideAutoContinueBar();
            state.autoContinueConfirmed = true;
            
            // 显示"继续"消息并重连到流
            // 保护：确保当前会话没有变化，避免会话混乱
            if (data.task_id && !state.currentEventSource && state.currentSession === currentSessionAtStart) {
                // 检查最后一条用户消息是否已经是"继续"（刷新页面后历史消息已加载）
                const lastUserMsg = [...document.querySelectorAll('.message.user')].pop();
                const lastUserText = lastUserMsg?.textContent?.trim();
                if (lastUserText !== '继续') {
                    addUserMessage('继续', []);
                }
                reconnectToTask(data.task_id);
            }
            return;
        }
        
        // auto_continue 类型特殊处理：显示倒计时条并启动轮询
        if (data.preview_type === 'auto_continue') {
            state.currentPendingPreviewId = previewId;
            showAutoContinueBar(remainingSeconds);
            // 确保轮询在运行（用于持续更新倒计时）
            if (!state.autoContinueTimer) {
                startAutoContinuePolling();
            }
            return;
        }
        
        // 如果已经显示了这个预览，只更新倒计时显示（从后端同步时间）
        if (state.currentPendingPreviewId === previewId) {
            const existingCard = document.querySelector(`[data-preview-id="${previewId}"]`);
            if (existingCard) {
                const countdownEl = existingCard.querySelector('.countdown');
                if (countdownEl && !countdownEl.classList.contains('expired')) {
                    if (remainingSeconds <= 0) {
                        // 倒计时结束，显示自动执行中
                        countdownEl.textContent = '⏱ 自动执行中...';
                        countdownEl.classList.add('expired');
                        countdownEl.classList.remove('warning');
                        existingCard.querySelectorAll('button').forEach(btn => btn.disabled = true);
                    } else {
                        countdownEl.textContent = `⏱ ${formatCountdown(remainingSeconds)}`;
                        countdownEl.dataset.seconds = remainingSeconds;
                        // 更新 warning 状态
                        if (remainingSeconds <= 30) {
                            countdownEl.classList.add('warning');
                        } else {
                            countdownEl.classList.remove('warning');
                        }
                    }
                }
            }
            return;
        }
        
        // 新预览卡片不应该在 remainingSeconds <= 0 时创建
        if (remainingSeconds <= 0) return;
        
        // 检查页面上是否已经有这个预览卡片（防止重复）
        if (document.querySelector(`[data-preview-id="${previewId}"]`)) return;
        
        state.currentPendingPreviewId = previewId;
        
        // 根据类型显示不同的预览卡片（始终在消息流中显示）
        if (data.preview_type === 'plan') {
            // 转换 subtasks 格式：后端返回字符串数组，前端需要对象数组
            const subtasksData = (data.subtasks || []).map(st => 
                typeof st === 'string' ? { name: st, state: 'todo' } : st
            );
            showPlanPreview({
                preview_id: previewId,
                name: data.name || data.preview.prompt,
                state: 'pending',
                subtasks: subtasksData,
            }, remainingSeconds);
        } else if (data.preview_type === 'ask_user') {
            showUserInputRequest({
                request_id: previewId,
                message: 'AI 正在等待您的输入...',
            }, remainingSeconds);
        } else {
            showKuncodePreview({
                preview_id: previewId,
                prompt: data.preview.prompt,
                agent: data.preview.agent,
                model: data.preview.model,
            }, remainingSeconds);
        }
        
        // 确保轮询在运行（用于检测超时自动执行）
        if (!state.pendingPreviewInterval) {
            startPendingPreviewPolling();
        }
        
        console.log(`加载预览: ${previewId}, 剩余 ${remainingSeconds} 秒`);
    } catch (err) {
        console.error('Load pending preview error:', err);
    }
}

// 开始轮询待确认预览（任务执行期间）
function startPendingPreviewPolling() {
    stopPendingPreviewPolling();
    state.pendingPreviewInterval = setInterval(() => {
        loadPendingPreview();
    }, 1000); // 每秒检查一次
}

// 停止轮询待确认预览
function stopPendingPreviewPolling() {
    if (state.pendingPreviewInterval) {
        clearInterval(state.pendingPreviewInterval);
        state.pendingPreviewInterval = null;
    }
    // 注意：不重置 currentPendingPreviewId，让 loadPendingPreview 检测到之前有预览
}

// ==================== 自动继续等待逻辑 ====================

// 显示自动继续倒计时条（后端计时，通过轮询更新）
function showAutoContinueBar(seconds = 180) {
    console.log('showAutoContinueBar called, seconds:', seconds);
    state.autoContinueConfirmed = false;
    
    // 如果用户最近重置过（5秒内），不用后端时间覆盖前端显示
    const timeSinceReset = Date.now() - lastAutoContinueResetTime;
    const userRecentlyActive = timeSinceReset < 5000;
    
    // 如果已经有倒计时条，只更新时间
    const existingBar = document.querySelector('.auto-continue-bar');
    if (existingBar) {
        const countdown = existingBar.querySelector('.countdown');
        // 如果用户最近活跃，不覆盖前端显示
        if (countdown && !userRecentlyActive) {
            if (seconds <= 0) {
                countdown.textContent = '自动继续中...';
            } else {
                countdown.textContent = formatCountdown(seconds);
            }
        }
        // 注意：时间到时不在前端触发，等待后端 Celery 任务设置 auto_triggered 状态
        // 轮询会检测到 auto_triggered 并自动重连
        return;
    }
    
    const bar = document.createElement('div');
    bar.className = 'auto-continue-bar';
    bar.innerHTML = `
        <span class="auto-continue-text">是否继续执行计划 (<span class="countdown">${formatCountdown(seconds)}</span>)</span>
        <div class="auto-continue-buttons">
            <button class="btn-cancel">取消</button>
            <button class="btn-continue">继续</button>
        </div>
    `;
    
    // 插入到输入区域内部的最前面
    const inputArea = $('.input-area');
    // console.log('inputArea found:', !!inputArea);
    if (inputArea) {
        inputArea.insertBefore(bar, inputArea.firstChild);
        console.log('auto-continue-bar inserted');
    }
    
    // 绑定按钮事件
    bar.querySelector('.btn-cancel').addEventListener('click', () => handleAutoContinueAction('cancel'));
    bar.querySelector('.btn-continue').addEventListener('click', () => handleAutoContinueAction('continue'));
}

// 格式化倒计时显示
function formatCountdown(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// 开始轮询自动继续状态（任务结束后调用）
function startAutoContinuePolling() {
    stopAutoContinuePolling();
    state.autoContinueTimer = setInterval(async () => {
        if (state.autoContinueConfirmed) {
            stopAutoContinuePolling();
            return;
        }
        await loadPendingPreview();
    }, 1000);
}

// 停止轮询自动继续状态
function stopAutoContinuePolling() {
    if (state.autoContinueTimer) {
        clearInterval(state.autoContinueTimer);
        state.autoContinueTimer = null;
    }
}

// 隐藏自动继续倒计时条
function hideAutoContinueBar(setConfirmed = false) {
    stopAutoContinuePolling();
    const bar = document.querySelector('.auto-continue-bar');
    if (bar) {
        bar.remove();
        // 只有明确要求时才设置已确认标志（用户点击按钮时）
        if (setConfirmed) {
            state.autoContinueConfirmed = true;
        }
    }
}

// 重置自动继续倒计时（用户输入时调用）
let resetTimerDebounce = null;
let lastAutoContinueResetTime = 0;  // 上次重置时间戳
function resetAutoContinueTimer() {
    if (!state.currentSession) return;
    
    // 如果有自动继续条正在显示，才重置
    const bar = document.querySelector('.auto-continue-bar');
    if (!bar) return;
    
    // 记录重置时间，用于阻止轮询覆盖
    lastAutoContinueResetTime = Date.now();
    
    // 立即重置前端倒计时显示为 3 分钟
    const countdown = bar.querySelector('.countdown');
    if (countdown) {
        countdown.textContent = formatCountdown(180);
    }
    
    // 防抖：10秒内只调用一次后端 API 重置 Celery 任务
    if (resetTimerDebounce) {
        clearTimeout(resetTimerDebounce);
    }
    resetTimerDebounce = setTimeout(async () => {
        try {
            await fetch(`/api/kuncode/${state.currentSession}/auto_continue/reset`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${Api.token}`,
                    'Content-Type': 'application/json',
                },
            });
        } catch (err) {
            console.error('Reset auto continue timer error:', err);
        }
    }, 10000);  // 10秒防抖，避免频繁调用后端
}

// 处理自动继续操作
async function handleAutoContinueAction(action) {
    hideAutoContinueBar(true);
    
    // 调用后端 API 确认/取消
    try {
        await fetch(`/api/kuncode/${state.currentSession}/auto_continue/confirm`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${Api.token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ action: action === 'cancel' ? 'cancel' : 'continue' }),
        });
    } catch (err) {
        console.error('Auto continue confirm error:', err);
    }
    
    if (action === 'cancel') {
        // 走中断逻辑（triggerUserInterrupt 会自动清空计划）
        await triggerUserInterrupt();
    } else if (action === 'continue' || action === 'auto') {
        // 发送"继续"消息
        await sendAutoContinueMessage('继续');
    }
}

// 发送自动继续消息
async function sendAutoContinueMessage(message) {
    if (!state.currentSession) return;
    
    // 添加用户消息到UI
    addUserMessage(message, []);
    
    // 切换到暂停按钮模式
    setSendButtonMode('pause');
    
    // 开始轮询待确认预览
    startPendingPreviewPolling();
    
    try {
        const task = await Api.submitTask(state.currentSession, message, []);
        const statusEl = addStatusMessage('继续执行中...');
        
        state.streamSessionId = state.currentSession;
        state.currentEventSource = Api.streamTask(task.task_id, (data) => {
            if (state.currentSession !== state.streamSessionId) return;
            if (statusEl && statusEl.parentNode) statusEl.remove();
            handleStreamData(data);
            scrollToBottom();
        }, (endData) => {
            const wasStreamSessionId = state.streamSessionId;
            state.currentEventSource = null;
            state.streamSessionId = null;
            setSendButtonMode('send');
            stopPendingPreviewPolling();
            
            if (state.currentSession !== wasStreamSessionId) return;
            
            if (endData.type === 'error') {
                addErrorMessage(endData.content);
            }
            if (state.stream.thinkingBlock) {
                state.stream.thinkingBlock.classList.remove('expanded');
            }
            finalizeRunningSandboxTools();
            addFinalTerminalPrompt();
            refreshSandboxFiles();
            loadSessions();
            refreshContextRing();
            forceScrollToBottom();
            
            // 检查是否需要再次显示自动继续
            checkAndShowAutoContinue();
        });
    } catch (err) {
        setSendButtonMode('send');
        addErrorMessage(err.message);
    }
}

// 刷新上下文使用量（流式结束后调用）
async function refreshContextRing() {
    if (!state.currentSession) return;
    try {
        const detail = await Api.getSession(state.currentSession);
        updateContextRing(detail.context_info);
    } catch (err) {
        console.error('Refresh context ring error:', err);
    }
}

// 检查并显示自动继续条（流式结束时调用）
// 改为启动轮询，由后端创建 auto_continue pending 状态
async function checkAndShowAutoContinue() {
    // 重置确认状态，允许新的轮询
    state.autoContinueConfirmed = false;
    // 启动轮询，后端会在计划未完成时创建 auto_continue pending
    startAutoContinuePolling();
}

// 断点续传：重新连接到正在执行的任务
function reconnectToTask(taskId) {
    // 添加状态提示
    const statusEl = addStatusMessage('正在继续执行...');
    
    // 切换到暂停按钮模式
    setSendButtonMode('pause');
    
    // 标记为重连模式（跳过历史的用户输入请求）
    state.isReconnecting = true;
    
    // 开始轮询待确认预览
    startPendingPreviewPolling();
    
    // 保存EventSource
    state.streamSessionId = state.currentSession;
    state.currentEventSource = Api.streamTask(taskId, (data) => {
        // 检查会话是否已变更
        if (state.currentSession !== state.streamSessionId) return;
        
        if (statusEl && statusEl.parentNode) statusEl.remove();
        handleStreamData(data);
        scrollToBottom();
    }, (endData) => {
        const wasStreamSessionId = state.streamSessionId;
        state.currentEventSource = null;
        state.streamSessionId = null;
        state.isReconnecting = false;  // 重置重连标记
        setSendButtonMode('send');
        stopPendingPreviewPolling();
        
        // 检查会话是否已变更
        if (state.currentSession !== wasStreamSessionId) return;
        
        if (statusEl && statusEl.parentNode) statusEl.remove();
        
        if (endData.type === 'error') {
            addErrorMessage(endData.content);
        }
        // Finalize thinking block
        if (state.stream.thinkingBlock) {
            state.stream.thinkingBlock.classList.remove('expanded');
        }
        finalizeRunningSandboxTools();
        addFinalTerminalPrompt();
        refreshSandboxFiles();
        loadSessions();
        refreshContextRing();
        forceScrollToBottom();
        
        // 检查是否需要显示自动继续
        checkAndShowAutoContinue();
    });
}

// 沙箱工具列表
const SANDBOX_TOOLS = ['run_kuncode', 'run_ipython_cell', 'run_shell_command', 'kuncode_session_list', 'kuncode_mcp_list', 'kuncode_agent_list'];
// 不在终端显示的工具（仅用于编辑prompt，不执行命令）
const NO_TERMINAL_TOOLS = ['kuncode_prd_update', 'ask_user', 'create_plan', 'finish_subtask', 'finish_plan', 'update_subtask_state', 'revise_current_plan'];

function renderMessages(messages) {
    const container = $('#messages');
    container.innerHTML = '';
    $('#terminal-body').innerHTML = '';
    
    // 用于匹配工具调用和结果
    const toolResults = {};
    
    // 先收集所有工具结果
    for (const m of messages) {
        if (m.role === 'system' && Array.isArray(m.content)) {
            for (const block of m.content) {
                if (block.type === 'data' && block.data?.output) {
                    toolResults[block.data.call_id] = block.data.output;
                }
            }
        }
    }
    
    // 渲染消息 - 使用msg_type区分消息类型
    const seenUserMsgs = new Set(); // 用于去重用户消息
    
    for (const m of messages) {
        if (m.role === 'system') continue; // 跳过系统消息，工具结果已收集
        
        const blocks = Array.isArray(m.content) ? m.content : [{ type: 'text', text: m.content }];
        const msgType = m.msg_type || 'message'; // reasoning, plugin_call, plugin_call_output, message
        
        if (m.role === 'user') {
            // 用户消息去重
            const textBlocks = blocks.filter(b => b.type === 'text' && b.text);
            if (textBlocks.length > 0) {
                let msgText = textBlocks[0].text;
                
                // 跳过已见过的消息
                if (seenUserMsgs.has(msgText)) continue;
                seenUserMsgs.add(msgText);
                
                // 使用 file_paths 显示文件（优先），否则回退到解析消息文本
                const filePaths = m.file_paths || [];
                
                if (filePaths.length > 0) {
                    // 从消息中移除系统提示部分，只显示用户原始消息
                    if (msgText.includes('[系统提示]')) {
                        const parts = msgText.split('\n\n[系统提示]');
                        msgText = parts[0].trim();
                    }
                    
                    const group = document.createElement('div');
                    group.className = 'msg-group user';
                    
                    // 显示文件
                    const filesDiv = document.createElement('div');
                    filesDiv.className = 'msg-files';
                    filesDiv.innerHTML = filePaths.map(filePath => {
                        const fileName = filePath.split('/').pop();
                        return `
                            <div class="msg-file">
                                <div class="file-icon">${getFileIcon(fileName)}</div>
                                <div class="file-info">
                                    <span class="file-name">${escapeHtml(fileName)}</span>
                                </div>
                            </div>
                        `;
                    }).join('');
                    group.appendChild(filesDiv);
                    
                    // 显示用户消息
                    if (msgText) {
                        const msgEl = document.createElement('div');
                        msgEl.className = 'message user';
                        msgEl.textContent = msgText;
                        group.appendChild(msgEl);
                    }
                    
                    container.appendChild(group);
                } else {
                    // 普通用户消息 - 检查是否有内嵌的文件信息（兼容旧消息格式）
                    if (msgText.includes('[系统提示]') && msgText.includes('已上传以下文件')) {
                        // 提取文件路径和用户消息
                        const fileMatch = msgText.match(/- ([^\n]+)/g);
                        const parts = msgText.split('\n\n[系统提示]');
                        const userMsgPart = parts[0].trim();
                        
                        const group = document.createElement('div');
                        group.className = 'msg-group user';
                        
                        // 显示文件
                        if (fileMatch && fileMatch.length > 0) {
                            const filesDiv = document.createElement('div');
                            filesDiv.className = 'msg-files';
                            filesDiv.innerHTML = fileMatch.map(f => {
                                const filePath = f.replace('- ', '').trim();
                                const fileName = filePath.split('/').pop();
                                return `
                                    <div class="msg-file">
                                        <div class="file-icon">${getFileIcon(fileName)}</div>
                                        <div class="file-info">
                                            <span class="file-name">${escapeHtml(fileName)}</span>
                                        </div>
                                    </div>
                                `;
                            }).join('');
                            group.appendChild(filesDiv);
                        }
                        
                        // 显示用户消息
                        if (userMsgPart) {
                            const msgEl = document.createElement('div');
                            msgEl.className = 'message user';
                            msgEl.textContent = userMsgPart;
                            group.appendChild(msgEl);
                        }
                        
                        container.appendChild(group);
                    } else {
                        // 纯文本消息
                        const el = document.createElement('div');
                        el.className = 'message user';
                        el.textContent = msgText;
                        container.appendChild(el);
                    }
                }
            }
        } else if (m.role === 'assistant') {
            // 根据msg_type区分thinking和普通text
            if (msgType === 'reasoning') {
                // Thinking内容 - 可折叠
                const textBlocks = blocks.filter(b => b.type === 'text' && b.text);
                if (textBlocks.length > 0) {
                    const thinkingBlock = createThinkingBlock(textBlocks[0].text, false);
                    container.appendChild(thinkingBlock);
                    // 记录历史thinking内容，用于断点续传时精确去重
                    state.stream.lastHistoryThinkingContent = textBlocks[0].text;
                }
            } else if (msgType === 'kuncode_preview') {
                // Kuncode 预览卡片（从历史记录加载）
                for (const block of blocks) {
                    if (block.type === 'kuncode_preview') {
                        renderKuncodePreviewFromHistory(container, block);
                    }
                }
            } else if (msgType === 'plugin_call') {
                // 工具调用
                for (const block of blocks) {
                    if (block.type === 'data' && block.data?.name) {
                        const toolName = block.data.name;
                        const callId = block.data.call_id;
                        const args = block.data.arguments;
                        const result = toolResults[callId];
                        
                        // 记录已显示的tool_id，用于断点续传时跳过
                        if (callId) {
                            state.stream.seenToolIds.add(callId);
                        }
                        
                        if (SANDBOX_TOOLS.includes(toolName) || toolName === 'preview_plan') {
                            // 创建可点击的工具调用块
                            const callId = block.data.call_id || `tool-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
                            const wrapper = document.createElement('div');
                            wrapper.className = 'tool-indicator-wrapper';
                            const indicator = document.createElement('div');
                            
                            if (toolName === 'preview_plan') {
                                // preview_plan 使用标准折叠块
                                indicator.className = 'tool-call-block';
                                // 解析工具结果：可能是 JSON 数组格式 [{"type":"text","text":"..."}]
                                let resultText = result;
                                try {
                                    const parsed = typeof result === 'string' ? JSON.parse(result) : result;
                                    if (Array.isArray(parsed)) {
                                        resultText = parsed.map(item => item.text || '').join('\n');
                                    }
                                } catch (e) { /* 保持原样 */ }
                                indicator.innerHTML = `
                                    <div class="tool-call-header">
                                        <span class="icon">🔧</span>
                                        <span class="name">${escapeHtml(toolName)}</span>
                                        <span class="status">已完成</span>
                                        <span class="toggle">▶</span>
                                    </div>
                                    <div class="tool-call-result">${renderMarkdown(resultText)}</div>
                                `;
                                indicator.querySelector('.tool-call-header').addEventListener('click', () => {
                                    indicator.classList.toggle('expanded');
                                });
                            } else {
                                // 沙箱工具使用闪电图标
                                indicator.className = 'sandbox-tool-indicator completed';
                                indicator.dataset.toolId = callId;
                                indicator.innerHTML = `<span class="icon">✓</span><span>${escapeHtml(toolName)}</span><span class="status">完成</span>`;
                                indicator.onclick = () => scrollToTerminalResult(callId);
                            }
                            
                            wrapper.appendChild(indicator);
                            container.appendChild(wrapper);
                            
                            // 不在终端显示的工具跳过
                            if (toolName !== 'preview_plan' && !NO_TERMINAL_TOOLS.includes(toolName)) {
                                addToTerminal(toolName, args, result, callId);
                            }
                        } else {
                            const toolBlock = createToolCallBlock(toolName, args, result);
                            container.appendChild(toolBlock);
                        }
                    }
                }
            } else {
                // 普通文本消息
                for (const block of blocks) {
                    if (block.type === 'text' && block.text) {
                        // 过滤DeepSeek的thinking结束标记
                        let cleanText = block.text.replace(/<｜end▁of▁thinking｜>/g, '').trim();
                        if (!cleanText) continue;
                        
                        // 中断消息统一显示为中文（居中样式）
                        if (cleanText.includes('I noticed that you have interrupted me')) {
                            const el = document.createElement('div');
                            el.className = 'message status';
                            el.style.backgroundColor = '#fef3c7';
                            el.style.color = '#92400e';
                            el.style.textAlign = 'center';
                            el.textContent = '执行已被用户中断';
                            container.appendChild(el);
                            continue;
                        }
                        
                        const el = document.createElement('div');
                        el.className = 'message assistant';
                        el.innerHTML = renderMarkdown(cleanText);
                        container.appendChild(el);
                        // 记录历史文本内容，用于断点续传时跳过
                        state.stream.lastHistoryTextContent = cleanText;
                    }
                }
            }
        }
    }
    container.scrollTop = container.scrollHeight;
    // 在历史消息渲染完成后添加prompt
    const terminal = $('#terminal-body');
    if (terminal.children.length > 0) {
        // 有终端命令，添加最终prompt
        addFinalTerminalPrompt();
    } else {
        // 没有终端命令，添加默认prompt
        addDefaultTerminalPrompt();
    }
    scrollTerminalToBottom();
}

// 添加到终端
function addToTerminal(toolName, argsStr, resultStr, callId) {
    const terminal = $('#terminal-body');
    
    // 检查是否已有此命令（防止重复）
    if (callId && $(`#term-cmd-${callId}`)) {
        return; // 已存在，跳过
    }
    
    // 解析参数获取命令
    let cmd = toolName;
    let isMultiLine = false;
    try {
        const args = JSON.parse(argsStr);
        if (toolName === 'run_shell_command' && args.command) {
            cmd = args.command;
            isMultiLine = cmd.includes('\n');
        } else if (toolName === 'run_ipython_cell' && args.code) {
            // 显示完整的 python 代码，保留换行
            cmd = `python -c "\n${args.code}`;
            isMultiLine = true;
        } else if (toolName === 'run_kuncode' && args.prompt) {
            cmd = `kuncode run "${args.prompt.substring(0, 200)}${args.prompt.length > 200 ? '...' : ''}"`;
        }
    } catch (e) {}
    
    // 命令行
    const line = document.createElement('div');
    line.className = 'terminal-line' + (isMultiLine ? ' multi-line-cmd' : '');
    if (callId) {
        line.id = `term-cmd-${callId}`;
        line.dataset.callId = callId;
    }
    // 多行命令：prompt 和第一行在同一行，后续行保留换行
    const cmdHtml = isMultiLine 
        ? `<pre class="cmd-block">${escapeHtml(cmd)}</pre>`
        : `<span class="cmd">${escapeHtml(cmd)}</span>`;
    line.innerHTML = `<span class="prompt"><span class="user">phantom</span><span class="at">@</span><span class="host">agent_sandbox</span>:~$ </span>${cmdHtml}`;
    terminal.appendChild(line);
    
    // 输出
    if (resultStr) {
        let output = '';
        try {
            const parsed = JSON.parse(resultStr);
            if (Array.isArray(parsed)) {
                output = parsed.map(p => p.text || '').join('');
            } else {
                output = resultStr;
            }
        } catch (e) {
            output = resultStr;
        }
        // 去掉末尾的退出码（如 \n0 或单独的 0）
        output = output.replace(/\n\d+$/, '');
        
        if (output) {
            const outLine = document.createElement('div');
            outLine.className = 'terminal-line terminal-output';
            if (callId) {
                outLine.id = `term-out-${callId}`;
                outLine.dataset.callId = callId;
            }
            // 使用ANSI颜色解析
            outLine.innerHTML = `<span class="output">${parseAnsiToHtml(output)}</span>`;
            terminal.appendChild(outLine);
        }
    }
}

// 在所有命令渲染完后添加最终prompt
function addFinalTerminalPrompt() {
    const terminal = $('#terminal-body');
    // 检查是否已有最终prompt，避免重复添加
    const existingFinal = terminal.querySelector('.terminal-prompt-final');
    if (existingFinal) return;
    
    const promptLine = document.createElement('div');
    promptLine.className = 'terminal-line terminal-prompt-final';
    promptLine.innerHTML = `<span class="prompt"><span class="user">phantom</span><span class="at">@</span><span class="host">agent_sandbox</span>:~$ </span>`;
    terminal.appendChild(promptLine);
}

// 点击工具名跳转到终端并高亮
function scrollToTerminalResult(callId) {
    // 切换到终端标签页
    $$('.tab-btn').forEach(btn => btn.classList.remove('active'));
    $$('.tab-content').forEach(tab => tab.classList.remove('active'));
    $('[data-tab="tools"]').classList.add('active');
    $('#tab-tools').classList.add('active');
    
    // 查找并高亮对应的终端行
    const lines = $$(`[data-call-id="${callId}"]`);
    if (lines.length > 0) {
        lines.forEach(line => {
            line.classList.add('highlight');
            setTimeout(() => line.classList.remove('highlight'), 2000);
        });
        // 滚动到该区域的开头位置
        lines[0].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function scrollTerminalToBottom() {
    const terminal = $('#terminal-body');
    if (terminal) terminal.scrollTop = terminal.scrollHeight;
}

// 创建非沙箱工具调用块（可折叠）
function createToolCallBlock(toolName, argsStr, resultStr) {
    const block = document.createElement('div');
    block.className = 'tool-call-block';
    
    let resultContent = '';
    if (resultStr) {
        try {
            const parsed = JSON.parse(resultStr);
            if (Array.isArray(parsed)) {
                resultContent = parsed.map(p => p.text || JSON.stringify(p)).join('\n');
            } else {
                resultContent = JSON.stringify(parsed, null, 2);
            }
        } catch (e) {
            resultContent = resultStr;
        }
    }
    
    block.innerHTML = `
        <div class="tool-call-header">
            <span class="icon">🔧</span>
            <span class="name">${escapeHtml(toolName)}</span>
            <span class="status">${resultStr ? '完成' : '执行中...'}</span>
            <span class="toggle">▶</span>
        </div>
        <div class="tool-call-result">${escapeHtml(resultContent)}</div>
    `;
    
    block.querySelector('.tool-call-header').addEventListener('click', () => {
        block.classList.toggle('expanded');
    });
    
    return block;
}

function parseMessageContent(content) {
    if (!content) return [];
    if (typeof content === 'string') {
        return [{ type: 'text', text: content }];
    }
    if (Array.isArray(content)) {
        return content;
    }
    // Single object
    return [content];
}

function isSystemHint(text) {
    if (!text) return false;
    return text.includes('[系统提示]') || text.includes('已上传以下文件到沙箱');
}

function createThinkingBlock(content, expanded = false) {
    // 过滤掉内部标记
    const cleanContent = (content || '')
        .replace(/<｜end▁of▁thinking｜>/g, '')
        .replace(/<｜DSML｜[\s\S]*$/g, '')
        .trim();
    
    const block = document.createElement('div');
    block.className = 'thinking-block' + (expanded ? ' expanded' : '');
    block.innerHTML = `
        <div class="thinking-header">
            <span class="toggle">▶</span>
            <span>💭 思考过程</span>
        </div>
        <div class="thinking-content">${escapeHtml(cleanContent)}</div>
    `;
    block.querySelector('.thinking-header').addEventListener('click', () => {
        block.classList.toggle('expanded');
    });
    return block;
}

const MARKDOWN_ALLOWED_TAGS = new Set([
    'a', 'b', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'i', 'li', 'ol', 'p', 'pre', 'strong', 'table',
    'tbody', 'td', 'th', 'thead', 'tr', 'ul'
]);
const MARKDOWN_DROPPED_TAGS = new Set([
    'embed', 'iframe', 'object', 'script', 'style', 'svg', 'template'
]);

function sanitizeMarkdownHtml(html) {
    const template = document.createElement('template');
    template.innerHTML = html;
    const elements = [];
    const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_ELEMENT);
    while (walker.nextNode()) elements.push(walker.currentNode);

    for (const element of elements) {
        const tagName = element.tagName.toLowerCase();
        if (MARKDOWN_DROPPED_TAGS.has(tagName)) {
            element.remove();
            continue;
        }
        if (!MARKDOWN_ALLOWED_TAGS.has(tagName)) {
            element.replaceWith(...Array.from(element.childNodes));
            continue;
        }

        for (const attribute of Array.from(element.attributes)) {
            const name = attribute.name.toLowerCase();
            const keepClass = name === 'class' && (tagName === 'code' || tagName === 'pre');
            if (!(tagName === 'a' && name === 'href') && !keepClass) {
                element.removeAttribute(attribute.name);
            }
        }

        if (tagName === 'a') {
            const href = element.getAttribute('href') || '';
            try {
                const url = new URL(href, window.location.origin);
                if (!['http:', 'https:', 'mailto:'].includes(url.protocol)) {
                    element.removeAttribute('href');
                }
            } catch (e) {
                element.removeAttribute('href');
            }
            element.setAttribute('target', '_blank');
            element.setAttribute('rel', 'noopener noreferrer');
        }
    }

    return template.innerHTML;
}

function renderMarkdown(text) {
    if (!text) return '';
    try {
        if (typeof marked !== 'undefined') {
            return sanitizeMarkdownHtml(marked.parse(text));
        }
    } catch (e) {}
    return sanitizeMarkdownHtml(escapeHtml(text).replace(/\n/g, '<br>'));
}


async function createNewSession() {
    try {
        // 断开当前流式连接（后台任务继续运行）
        disconnectCurrentStream();
        
        const res = await Api.createSession();
        state.currentSession = res.session_id;
        await loadSessions();
        $('#messages').innerHTML = '';
        state.pendingFiles = [];
        state.uploadedFileIds = [];
        state.stream = {
            thinkingBlock: null,
            assistantEl: null,
            currentToolId: null,
            currentToolName: null,
            currentToolBlock: null,
            toolNames: new Map(),
            seenToolIds: new Set(),
            terminalCommands: new Set(),
            lastThinkingContent: null
        };
        // 清空右侧面板状态
        clearRightPanelState();
        updateFilePreview();
        refreshSandboxFiles();
        // 新建会话时上下文置零
        updateContextRing({ estimated_tokens: 0, max_tokens: 120000, usage_percent: 0 });
    } catch (err) {
        console.error('Create session error:', err);
    }
}

// Sandbox Files
function startFilesRefresh() {
    stopFilesRefresh();
    state.filesRefreshInterval = setInterval(refreshSandboxFiles, 5000);
}

function stopFilesRefresh() {
    if (state.filesRefreshInterval) {
        clearInterval(state.filesRefreshInterval);
        state.filesRefreshInterval = null;
    }
}

// 当前浏览路径
state.currentPath = '';
state.viewingFile = null;

async function refreshSandboxFiles() {
    if (!state.currentSession) {
        $('#sandbox-files').innerHTML = '<div class="empty-state">无会话</div>';
        return;
    }
    // 如果正在查看文件内容，不要刷新
    if (state.viewingFile) {
        return;
    }
    // 保持当前路径，只刷新当前目录
    await loadDirectory(state.currentPath || '');
}

// 加载目录
async function loadDirectory(path, preserveScroll = false) {
    const isRefresh = preserveScroll || (state.currentPath === path);
    state.currentPath = path;
    state.viewingFile = null;
    
    // 更新面包屑
    updateBreadcrumb(path);
    
    // 显示文件列表，隐藏文件内容
    $('#sandbox-files-container').classList.remove('hidden');
    $('#file-content-view').classList.add('hidden');
    
    const container = $('#sandbox-files');
    
    // 保存滚动位置（仅刷新时）
    const scrollTop = isRefresh ? container.scrollTop : 0;
    
    // 只有非刷新时才显示加载中
    if (!isRefresh) {
        container.innerHTML = '<div class="empty-state">加载中...</div>';
    }
    
    try {
        const files = await Api.listSandboxWorkspace(state.currentSession, path);
        if (!files || files.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无文件</div>';
        } else {
            container.innerHTML = renderFileList(files);
            bindFileListEvents();
            // 恢复滚动位置
            if (isRefresh) {
                container.scrollTop = scrollTop;
            }
        }
    } catch (err) {
        if (err.message.includes('未找到')) {
            container.innerHTML = '<div class="empty-state">沙箱未启动</div>';
        } else {
            container.innerHTML = '<div class="empty-state">加载失败</div>';
        }
    }
}

// 更新面包屑导航
function updateBreadcrumb(path) {
    const breadcrumb = $('#files-breadcrumb');
    let html = '<span class="crumb" data-path="">workspace</span>';
    
    if (path) {
        const parts = path.split('/');
        let currentPath = '';
        for (let i = 0; i < parts.length; i++) {
            currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i];
            html += `<span class="separator">/</span>`;
            html += `<span class="crumb" data-path="${escapeHtml(currentPath)}">${escapeHtml(parts[i])}</span>`;
        }
    }
    
    breadcrumb.innerHTML = html;
    
    // 标记最后一个为active
    const crumbs = breadcrumb.querySelectorAll('.crumb');
    crumbs.forEach((c, i) => {
        if (i === crumbs.length - 1) {
            c.classList.add('active');
        } else {
            c.classList.remove('active');
            c.addEventListener('click', () => loadDirectory(c.dataset.path));
        }
    });
}

// 渲染文件列表（扁平，不递归展开）
function renderFileList(items) {
    return items.map(item => {
        if (item.type === 'directory') {
            const isSpecialFolder = ['results', 'reports'].includes(item.name);
            const starIcon = isSpecialFolder ? ' <span class="folder-star">☆</span>' : '';
            return `
                <div class="file-item folder" data-type="directory" data-path="${escapeHtml(item.path)}">
                    <span class="icon"><span class="folder-icon">📁</span></span>
                    <span class="name">${escapeHtml(item.name)}${starIcon}</span>
                </div>
            `;
        } else {
            return `
                <div class="file-item" data-type="file" data-path="${escapeHtml(item.path)}">
                    <span class="icon">${getFileIcon(item.name)}</span>
                    <span class="name">${escapeHtml(item.name)}</span>
                    <span class="size">${formatFileSize(item.size)}</span>
                    <button class="download-btn" data-path="${escapeHtml(item.path)}" title="下载">↓</button>
                </div>
            `;
        }
    }).join('');
}

// 绑定文件列表事件
function bindFileListEvents() {
    const container = $('#sandbox-files');
    
    // 文件夹点击 - 进入目录
    container.querySelectorAll('.file-item.folder').forEach(folder => {
        folder.addEventListener('click', () => {
            loadDirectory(folder.dataset.path);
        });
    });
    
    // 文件点击 - 查看内容
    container.querySelectorAll('.file-item[data-type="file"]').forEach(item => {
        item.addEventListener('click', (e) => {
            if (e.target.closest('.download-btn')) return;
            viewFileContent(item.dataset.path);
        });
    });
    
    // 下载按钮
    container.querySelectorAll('.download-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            downloadSandboxFile(state.currentSession, btn.dataset.path);
        });
    });
}

// 查看文件内容
async function viewFileContent(path) {
    state.viewingFile = path;
    
    // 更新面包屑显示文件路径
    updateBreadcrumb(path);
    
    // 隐藏文件列表，显示文件内容
    $('#sandbox-files-container').classList.add('hidden');
    $('#file-content-view').classList.remove('hidden');
    
    const nameEl = $('#file-content-name');
    const bodyEl = $('#file-content-body');
    const downloadBtn = $('#file-content-download');
    
    nameEl.textContent = path.split('/').pop();
    bodyEl.innerHTML = '<div class="empty-state">加载中...</div>';
    
    // 绑定下载按钮
    downloadBtn.onclick = () => downloadSandboxFile(state.currentSession, path);
    
    try {
        const data = await Api.getSandboxFileContent(state.currentSession, path);
        
        if (data.image) {
            // 图片文件 - 直接显示
            const rawUrl = `/api/files/sandbox/${state.currentSession}/workspace/raw?path=${encodeURIComponent(path)}`;
            bodyEl.innerHTML = `
                <div class="image-preview">
                    <img src="${rawUrl}" alt="${path}" style="max-width: 100%; max-height: 500px; object-fit: contain;" />
                </div>
            `;
        } else if (data.html) {
            // HTML 文件 - iframe 渲染 + 全屏按钮 + 编辑按钮
            const rawUrl = `/api/files/sandbox/${state.currentSession}/workspace/raw?path=${encodeURIComponent(path)}`;
            const editorUrl = `/html-editor.html?session=${encodeURIComponent(state.currentSession)}&path=${encodeURIComponent(path)}`;
            
            // 处理 HTML 内容中的相对路径图片
            const fileDir = path.substring(0, path.lastIndexOf('/') + 1);
            let processedHtml = data.content || '';
            processedHtml = processedHtml.replace(
                /(<img[^>]*\ssrc=["'])(?!https?:\/\/|data:|\/api\/)([^"']+)(["'][^>]*>)/gi,
                (match, prefix, src, suffix) => {
                    const fullPath = fileDir + src;
                    const apiUrl = `/api/files/sandbox/${state.currentSession}/workspace/raw?path=${encodeURIComponent(fullPath)}`;
                    return prefix + apiUrl + suffix;
                }
            );
            
            bodyEl.innerHTML = `
                <div class="html-preview">
                    <div class="html-preview-actions">
                        <button class="btn-primary" onclick="window.open('${rawUrl}', '_blank')">🔗 新窗口打开</button>
                        <button class="btn-secondary" onclick="window.open('${editorUrl}', '_blank')">✏️ 编辑</button>
                    </div>
                    <iframe id="html-preview-iframe" style="width: 100%; height: 400px; border: 1px solid #ddd; border-radius: 4px; background: white;"></iframe>
                </div>
            `;
            
            // 使用 srcdoc 或 doc.write 渲染处理后的 HTML
            const previewIframe = bodyEl.querySelector('#html-preview-iframe');
            const iframeDoc = previewIframe.contentDocument || previewIframe.contentWindow.document;
            iframeDoc.open();
            iframeDoc.write(processedHtml);
            iframeDoc.close();
        } else if (data.binary) {
            const ext = path.split('.').pop().toLowerCase();
            const MAX_EXCEL_SIZE = 5 * 1024 * 1024; // 5MB
            
            // Excel 文件使用 SheetJS 渲染（限制 5MB 以内）
            if (['xlsx', 'xls'].includes(ext) && typeof XLSX !== 'undefined' && data.size <= MAX_EXCEL_SIZE) {
                try {
                    const rawUrl = `/api/files/sandbox/${state.currentSession}/workspace/raw?path=${encodeURIComponent(path)}`;
                    const res = await fetch(rawUrl, { headers: { 'Authorization': `Bearer ${Api.token}` } });
                    const arrayBuffer = await res.arrayBuffer();
                    const workbook = XLSX.read(arrayBuffer, { type: 'array' });
                    const sheetName = workbook.SheetNames[0];
                    const sheet = workbook.Sheets[sheetName];
                    const htmlTable = XLSX.utils.sheet_to_html(sheet, { editable: false });
                    
                    // Sheet 选择器
                    const sheetTabs = workbook.SheetNames.map((name, i) => 
                        `<button class="sheet-tab ${i === 0 ? 'active' : ''}" data-sheet="${escapeHtml(name)}">${escapeHtml(name)}</button>`
                    ).join('');
                    
                    bodyEl.innerHTML = `
                        <div class="excel-viewer">
                            <div class="sheet-tabs">${sheetTabs}</div>
                            <div class="excel-table-container">${htmlTable}</div>
                        </div>
                    `;
                    
                    // 绑定 sheet 切换事件
                    bodyEl.querySelectorAll('.sheet-tab').forEach(tab => {
                        tab.onclick = () => {
                            const name = tab.dataset.sheet;
                            const s = workbook.Sheets[name];
                            bodyEl.querySelector('.excel-table-container').innerHTML = XLSX.utils.sheet_to_html(s, { editable: false });
                            bodyEl.querySelectorAll('.sheet-tab').forEach(t => t.classList.remove('active'));
                            tab.classList.add('active');
                        };
                    });
                } catch (e) {
                    bodyEl.innerHTML = `<div class="empty-state">Excel 解析失败: ${e.message}</div>`;
                }
            } else {
                bodyEl.innerHTML = `
                    <div class="binary-file-notice">
                        <p>📄 二进制文件无法预览</p>
                        <p>文件大小: ${formatFileSize(data.size)}</p>
                        <button class="btn-primary" onclick="downloadSandboxFile('${state.currentSession}', '${path}')">下载文件</button>
                    </div>
                `;
            }
        } else {
            const ext = path.split('.').pop().toLowerCase();
            
            // CSV 文件渲染为表格
            if (ext === 'csv') {
                const tableHtml = renderCsvAsTable(data.content);
                bodyEl.innerHTML = `<div class="csv-table-container">${tableHtml}</div>`;
            } else {
                // 代码文件渲染 - 使用 Prism.js 语法高亮
                const langMap = {
                    'py': 'python', 'js': 'javascript', 'ts': 'typescript',
                    'html': 'markup', 'css': 'css', 'json': 'json', 'md': 'markdown',
                    'sql': 'sql', 'sh': 'bash', 'yml': 'yaml', 'yaml': 'yaml',
                    'txt': 'plaintext', 'log': 'plaintext',
                };
                const lang = langMap[ext] || 'plaintext';
                
                // 使用 Prism.js 高亮
                let highlighted = escapeHtml(data.content);
                if (typeof Prism !== 'undefined' && Prism.languages[lang]) {
                    highlighted = Prism.highlight(data.content, Prism.languages[lang], lang);
                }
                
                // 添加行号（不用 \n 连接，避免 pre 内额外空白）
                const lines = highlighted.split('\n');
                const numberedContent = lines.map((line, i) => 
                    `<div class="line"><span class="line-number">${i + 1}</span><span class="line-content">${line || ' '}</span></div>`
                ).join('');
                
                bodyEl.innerHTML = `<div class="code-preview"><code class="language-${lang}">${numberedContent}</code></div>`;
            }
        }
    } catch (err) {
        bodyEl.innerHTML = `<div class="empty-state">加载失败: ${err.message}</div>`;
    }
}

// 下载整个工作目录为ZIP
async function downloadWorkspaceZip() {
    if (!state.currentSession) {
        alert('请先选择会话');
        return;
    }
    try {
        const url = `/api/files/sandbox/${state.currentSession}/workspace/zip`;
        const res = await fetch(url, {
            headers: { 'Authorization': `Bearer ${Api.token}` }
        });
        if (!res.ok) throw new Error('下载失败');
        
        const blob = await res.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `workspace_${state.currentSession.substring(0, 8)}.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(downloadUrl);
    } catch (err) {
        console.error('Download zip error:', err);
        alert('下载失败: ' + err.message);
    }
}

// 下载沙箱文件（带认证）
async function downloadSandboxFile(sessionId, path) {
    try {
        const url = `/api/files/sandbox/${sessionId}/workspace/download?path=${encodeURIComponent(path)}`;
        const res = await fetch(url, {
            headers: { 'Authorization': `Bearer ${Api.token}` }
        });
        if (!res.ok) throw new Error('下载失败');
        
        const blob = await res.blob();
        const filename = path.split('/').pop();
        const downloadUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(downloadUrl);
    } catch (err) {
        console.error('Download error:', err);
        alert('下载失败: ' + err.message);
    }
}

// File Upload
function handleFileSelect(e) {
    const files = Array.from(e.target.files);
    state.pendingFiles.push(...files);
    updateFilePreview();
    e.target.value = '';
}

function updateFilePreview() {
    const container = $('#file-preview');
    if (state.pendingFiles.length === 0) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    container.innerHTML = state.pendingFiles.map((f, i) => `
        <div class="file-tag">
            <span>📎 ${escapeHtml(f.name)}</span>
            <button data-index="${i}">&times;</button>
        </div>
    `).join('');

    container.querySelectorAll('button').forEach(btn => {
        btn.addEventListener('click', () => {
            state.pendingFiles.splice(parseInt(btn.dataset.index), 1);
            updateFilePreview();
        });
    });
}

// Chat
async function sendMessage() {
    // 如果 AI 正在回答或正在提交中，不允许发送新消息
    if (state.currentEventSource || state.isSubmitting) {
        return;
    }
    
    // 立即标记为提交中，防止重复点击
    state.isSubmitting = true;
    setSendButtonMode('loading');
    
    // 用户主动发送消息时，隐藏自动继续条并通知后端
    const hasAutoContinueBar = !!document.querySelector('.auto-continue-bar');
    hideAutoContinueBar(true);
    if (hasAutoContinueBar && state.currentSession) {
        // 通知后端用户已发送消息，取消自动继续
        fetch(`/api/kuncode/${state.currentSession}/auto_continue/confirm`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${Api.token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ action: 'continue' }),
        }).catch(err => console.error('Auto continue confirm error:', err));
    }

    const input = $('#message-input');
    const message = input.value.trim();
    if (!message) {
        state.isSubmitting = false;
        setSendButtonMode('send');
        return;
    }

    // Ensure session exists
    if (!state.currentSession) {
        await createNewSession();
    }

    // Upload pending files first
    let uploadedFiles = [];
    if (state.pendingFiles.length > 0) {
        try {
            uploadedFiles = await Api.uploadFiles(state.currentSession, state.pendingFiles);
            state.uploadedFiles = uploadedFiles;
            state.pendingFiles = [];
            updateFilePreview();
        } catch (err) {
            state.isSubmitting = false;
            setSendButtonMode('send');
            addErrorMessage('文件上传失败: ' + err.message);
            return;
        }
    }

    // Add user message with files to UI
    addUserMessage(message, uploadedFiles);
    input.value = '';
    input.style.height = 'auto';

    // 切换到暂停按钮模式，并重置提交状态
    state.isSubmitting = false;
    setSendButtonMode('pause');
    
    // 开始轮询待确认预览
    startPendingPreviewPolling();

    // Reset streaming state
    state.stream = {
        thinkingBlock: null,
        assistantEl: null,
        currentToolId: null,
        currentToolName: null,
        currentToolBlock: null,
        toolNames: new Map(),
        seenToolIds: new Set(),  // 用于tool_call去重
        terminalCommands: new Set(),  // 用于终端命令去重
        lastThinkingContent: null,
        lastTextContent: null,  // 用于text去重
    };
    // 注意：不再清空终端，同一会话的终端内容应该保留
    // 只移除之前的最终prompt（如果有）
    const finalPrompt = $('#terminal-body .terminal-prompt-final');
    if (finalPrompt) finalPrompt.remove();

    try {
        // Submit async task
        const fileIds = uploadedFiles.map(f => f.id);
        const task = await Api.submitTask(state.currentSession, message, fileIds);
        state.uploadedFiles = [];

        // Add status message
        const statusEl = addStatusMessage('沙箱启动中...');

        // Stream response - 保存EventSource以便取消
        state.streamSessionId = state.currentSession;
        state.currentEventSource = Api.streamTask(task.task_id, (data) => {
            // 检查会话是否已变更
            if (state.currentSession !== state.streamSessionId) return;
            
            if (statusEl && statusEl.parentNode) statusEl.remove();
            handleStreamData(data);
            scrollToBottom();
        }, (endData) => {
            const wasStreamSessionId = state.streamSessionId;
            state.currentEventSource = null;
            state.streamSessionId = null;
            setSendButtonMode('send');
            stopPendingPreviewPolling();
            
            // 检查会话是否已变更
            if (state.currentSession !== wasStreamSessionId) return;
            
            if (endData.type === 'error') {
                addErrorMessage(endData.content);
            }
            // Finalize thinking block (collapse it)
            if (state.stream.thinkingBlock) {
                state.stream.thinkingBlock.classList.remove('expanded');
            }
            finalizeRunningSandboxTools();
            // 流式结束后添加最终prompt
            addFinalTerminalPrompt();
            refreshSandboxFiles();
            loadSessions();
            refreshContextRing();
            forceScrollToBottom();
            
            // 检查是否需要显示自动继续
            checkAndShowAutoContinue();
        });

    } catch (err) {
        state.isSubmitting = false;
        setSendButtonMode('send');
        addErrorMessage(err.message);
    }
}

// Handle streaming data - backend sends CUMULATIVE content
function handleStreamData(data) {
    const s = state.stream;
    
    // Filter system hints
    if (isSystemHint(data.content)) return;
    
    switch (data.type) {
        case 'thinking':
            // Thinking块内容去重 - 只在内容真正变化时更新
            // 过滤掉内部标记：end_of_thinking 和 DSML函数调用标记
            let thinkingContent = (data.content || '')
                .replace(/<｜end▁of▁thinking｜>/g, '')
                .replace(/<｜DSML｜[\s\S]*$/g, '')  // 移除DSML标记及之后的内容
                .trim();
            if (!thinkingContent) break;
            
            // 断点续传模式：检查页面上是否已存在相同或包含此内容的thinking块
            if (state.isReconnecting) {
                const existingBlocks = $$('.thinking-block .thinking-content');
                for (const block of existingBlocks) {
                    const existingText = block.textContent || '';
                    // 如果已有块包含此内容（或完全相同），跳过
                    if (existingText === thinkingContent || existingText.startsWith(thinkingContent)) {
                        // 跳过重复内容
                        return;
                    }
                }
            }
            
            // 断点续传时跳过已在历史中显示的thinking内容
            if (s.lastHistoryThinkingContent) {
                // 新内容是历史内容的前缀或相同，跳过
                if (s.lastHistoryThinkingContent.startsWith(thinkingContent) || 
                    thinkingContent === s.lastHistoryThinkingContent) {
                    break;
                }
            }
            
            // 如果内容与上次折叠的thinking相同，跳过（tool_call期间会重复发送相同thinking）
            if (s.lastThinkingContent && thinkingContent === s.lastThinkingContent) {
                break;
            }
            
            if (!s.thinkingBlock) {
                // 检查是否已存在相同内容的thinking块（避免重复）
                const existingBlocks = $$('.thinking-block .thinking-content');
                const lastBlock = existingBlocks[existingBlocks.length - 1];
                if (lastBlock && lastBlock.textContent === thinkingContent) {
                    // 内容相同，跳过
                    break;
                }
                // 如果是断点续传，清除历史标记，后续thinking都创建新块
                if (s.lastHistoryThinkingContent) {
                    s.lastHistoryThinkingContent = null;
                }
                // 创建新的thinking块
                s.thinkingBlock = createThinkingBlock('', true);
                $('#messages').appendChild(s.thinkingBlock);
                // 清除lastThinkingContent因为我们开始了新的thinking
                s.lastThinkingContent = null;
            }
            const thinkingEl = s.thinkingBlock.querySelector('.thinking-content');
            if (thinkingEl) {
                // 只有内容变化时才更新
                if (thinkingEl.textContent !== thinkingContent) {
                    thinkingEl.textContent = thinkingContent;
                }
            }
            break;

        case 'text':
            // 过滤掉DSML函数调用标记内容
            let textContent = (data.content || '')
                .replace(/<｜DSML｜[\s\S]*$/g, '')
                .trim();
            // 如果过滤后内容为空或只包含DSML，跳过
            if (!textContent || textContent.includes('<｜DSML｜')) break;
            
            // 断点续传时跳过已在历史中显示的文本内容
            // 检查流式内容是否是历史内容的前缀或完全匹配（正在"追赶"历史）
            if (s.lastHistoryTextContent) {
                // 如果流式内容是历史内容的前缀，说明还在追赶历史，跳过渲染
                if (s.lastHistoryTextContent.startsWith(textContent)) {
                    // 复用最后一个助手消息元素
                    const lastAssistant = document.querySelector('#messages .message.assistant:last-of-type');
                    if (lastAssistant) {
                        // 如果之前创建了流式元素且不是历史元素，移除它（防止重复显示）
                        if (s.assistantEl && s.assistantEl !== lastAssistant && s.assistantEl.parentNode) {
                            s.assistantEl.remove();
                        }
                        s.assistantEl = lastAssistant;
                    }
                    // 同步设置 lastTextContent，确保后续相同内容也能被去重
                    s.lastTextContent = textContent;
                    break;
                }
                // 流式内容已超过历史内容，清除历史标记，开始正常渲染新内容
                if (textContent.length > s.lastHistoryTextContent.length) {
                    s.lastHistoryTextContent = null;
                }
            }
            
            // 去重：如果内容与上次相同，跳过（防止工具调用后重复输出）
            if (s.lastTextContent && textContent === s.lastTextContent) break;
            s.lastTextContent = textContent;
            
            // Collapse thinking when text starts
            if (s.thinkingBlock) {
                s.thinkingBlock.classList.remove('expanded');
                s.thinkingBlock = null;
            }
            
            if (!s.assistantEl) {
                s.assistantEl = document.createElement('div');
                s.assistantEl.className = 'message assistant';
                $('#messages').appendChild(s.assistantEl);
            }
            s.assistantEl.innerHTML = renderMarkdown(textContent);
            break;

        case 'tool_call':
            // 只在首次遇到新tool_id时折叠thinking
            const toolName = data.content;
            const toolId = data.tool_id || `tool_${Date.now()}`;
            
            // 始终更新当前工具信息，用于后续 tool_result 路由
            s.currentToolId = toolId;
            s.currentToolName = toolName;
            if (!s.toolNames) s.toolNames = new Map();
            s.toolNames.set(toolId, toolName);
            
            // preview_plan 特殊处理：流式数据会多次到达，需要累积最新数据
            if (toolName === 'preview_plan' && data.input) {
                // 保存最新的完整数据（流式传输中会逐渐变完整）
                s.pendingPlanPreview = {
                    toolId: toolId,
                    name: data.input.name || '',
                    subtasks: data.input.subtasks || [],
                };
                // 首次出现时创建工具指示器
                if (!s.seenToolIds.has(toolId)) {
                    s.seenToolIds.add(toolId);
                    // 折叠 thinking
                    if (s.thinkingBlock) {
                        s.thinkingBlock.classList.remove('expanded');
                        s.thinkingBlock = null;
                    }
                    s.assistantEl = null;
                    // 创建工具指示器
                    const wrapper = document.createElement('div');
                    wrapper.className = 'tool-indicator-wrapper';
                    const indicator = document.createElement('div');
                    indicator.className = 'tool-call-block';
                    indicator.dataset.toolId = toolId;
                    indicator.innerHTML = `
                        <div class="tool-call-header">
                            <span class="icon">🔧</span>
                            <span class="name">${escapeHtml(toolName)}</span>
                            <span class="status">执行中...</span>
                            <span class="toggle">▶</span>
                        </div>
                        <div class="tool-call-result"></div>
                    `;
                    indicator.querySelector('.tool-call-header').addEventListener('click', () => {
                        indicator.classList.toggle('expanded');
                    });
                    wrapper.appendChild(indicator);
                    $('#messages').appendChild(wrapper);
                    s.currentToolBlock = indicator;
                }
                break;
            }
            
            // 基于tool_id去重 - 只在首次出现时创建UI元素
            if (s.seenToolIds.has(toolId)) {
                // 已存在，只更新终端命令（如果input有变化）
                if (SANDBOX_TOOLS.includes(toolName) && data.input) {
                    updateTerminalCommand(toolId, toolName, data.input);
                }
                break;
            }
            s.seenToolIds.add(toolId);
            
            // 只在首次处理新工具时折叠thinking块
            if (s.thinkingBlock) {
                s.thinkingBlock.classList.remove('expanded');
                // 记录最后的thinking内容，用于去重
                const lastContent = s.thinkingBlock.querySelector('.thinking-content')?.textContent || '';
                s.lastThinkingContent = lastContent;
                s.thinkingBlock = null;
            }
            s.assistantEl = null;
            
            if (SANDBOX_TOOLS.includes(toolName)) {
                // 沙箱工具 - 简单指示器 + 终端
                // 检查是否已有此工具的指示器（防止断点续传重复）
                const existingIndicator = $(`.sandbox-tool-indicator[data-tool-id="${toolId}"]`) ||
                                          $(`.sandbox-tool-indicator[data-call-id="${toolId}"]`);
                if (!existingIndicator) {
                    // 用wrapper确保独占一行
                    const wrapper = document.createElement('div');
                    wrapper.className = 'tool-indicator-wrapper';
                    const indicator = document.createElement('div');
                    indicator.className = 'sandbox-tool-indicator running';
                    indicator.dataset.toolId = toolId;
                    indicator.innerHTML = `<span class="icon">⚡</span><span>${escapeHtml(toolName)}</span><span class="status">运行中</span>`;
                    indicator.onclick = () => scrollToTerminalResult(toolId);
                    wrapper.appendChild(indicator);
                    $('#messages').appendChild(wrapper);
                }
                
                // 检查终端是否已有此命令（防止断点续传重复）
                const existingTermCmd = $(`#term-cmd-${toolId}`) || $(`[data-call-id="${toolId}"]`);
                if (!existingTermCmd) {
                    addTerminalCommand(toolName, data.input, toolId);
                }
                // 切换到终端tab
                switchToToolsTab();
            } else {
                // 其他非沙箱工具 - 可折叠块
                s.currentToolBlock = document.createElement('div');
                s.currentToolBlock.className = 'tool-call-block';
                s.currentToolBlock.dataset.toolId = toolId;
                s.currentToolBlock.innerHTML = `
                    <div class="tool-call-header">
                        <span class="icon">🔧</span>
                        <span class="name">${escapeHtml(toolName)}</span>
                        <span class="status">执行中...</span>
                        <span class="toggle">▶</span>
                    </div>
                    <div class="tool-call-result"></div>
                `;
                s.currentToolBlock.querySelector('.tool-call-header').addEventListener('click', () => {
                    s.currentToolBlock.classList.toggle('expanded');
                });
                $('#messages').appendChild(s.currentToolBlock);
            }
            break;

        case 'tool_result':
            const resultToolId = data.tool_id || s.currentToolId;
            let resultToolName = (s.toolNames && resultToolId ? s.toolNames.get(resultToolId) : '') || s.currentToolName || '';
            
            // 如果当前没有工具名（重连场景），尝试从DOM查找
            if (!resultToolName && resultToolId) {
                // 检查终端是否有此工具的命令（说明是沙箱工具）
                const termCmd = $(`#term-cmd-${resultToolId}`) || $(`[data-call-id="${resultToolId}"]`);
                if (termCmd) {
                    resultToolName = 'run_kuncode'; // 终端命令存在，标记为沙箱工具
                }
            }
            
            if (SANDBOX_TOOLS.includes(resultToolName)) {
                // 沙箱工具 - 更新终端输出（使用 resultToolId 确保正确关联）
                updateTerminalOutputById(resultToolId, data.content);
                markSandboxToolFinished(resultToolId, data.content);
            } else if (s.currentToolBlock) {
                // 非沙箱工具 - 更新结果
                const resultEl = s.currentToolBlock.querySelector('.tool-call-result');
                const statusEl = s.currentToolBlock.querySelector('.status');
                if (resultEl) resultEl.textContent = data.content;
                if (statusEl) statusEl.textContent = '完成';
            }
            // 工具执行完成后清除lastThinkingContent，允许新的thinking周期
            s.lastThinkingContent = null;
            break;

        case 'plan':
            // 计划更新事件（已确认后的最终显示）
            updatePlanDisplay(data);
            // 自动切换到计划标签页
            switchToPlanTab();
            break;

        case 'plan_preview':
            // 计划预览事件 - 显示预览卡片等待用户确认（使用后端返回的剩余时间）
            // 重连模式下跳过，让 loadPendingPreview 通过 /pending API 决定是否显示
            if (state.isReconnecting) {
                break;
            }
            showPlanPreview(data, data.remaining_seconds || 180);
            break;

        case 'plan_confirmed':
            // 计划已确认 - 更新预览卡片状态
            updatePlanPreviewStatus(data.preview_id, 'confirmed', data.auto_confirm);
            break;

        case 'kuncode_preview':
            // Kuncode 预览事件 - 显示预览卡片等待用户确认（使用后端返回的剩余时间）
            // 重连模式下跳过，让 loadPendingPreview 通过 /pending API 决定是否显示
            if (state.isReconnecting) {
                break;
            }
            showKuncodePreview(data, data.remaining_seconds || 180);
            break;

        case 'kuncode_confirmed':
            // Kuncode 已确认 - 更新预览卡片状态
            updateKuncodePreviewStatus(data.preview_id, 'executing', data.prompt);
            break;

        case 'user_input_required':
            // AI 请求用户输入（使用后端返回的剩余时间）
            // 断点续传时跳过历史的用户输入请求（由 loadPendingPreview 处理真正的 pending）
            if (state.isReconnecting) {
                // 重连模式下跳过，让 loadPendingPreview 处理
                break;
            }
            if (!s.processedUserInputIds.has(data.request_id)) {
                showUserInputRequest(data, data.remaining_seconds || 180);
            }
            break;

        case 'user_input_received':
            // 用户已输入 - 标记为已处理
            s.processedUserInputIds.add(data.request_id);
            // 重连模式下收到此事件，说明是历史事件，结束重连模式
            if (state.isReconnecting) {
                state.isReconnecting = false;
            }
            // 如果卡片存在则更新状态，否则忽略
            const existingCard = document.getElementById(`user-input-request-${data.request_id}`);
            if (existingCard) {
                updateUserInputStatus(data.request_id, 'received', data.content);
            }
            break;

        case 'step_complete':
            // 步骤完成后清除lastThinkingContent，允许新的thinking周期
            s.lastThinkingContent = null;
            // 计划预览由 plan_preview 事件处理，不在这里显示
            s.pendingPlanPreview = null;
            // 更新上下文使用量
            if (data.context_info) {
                updateContextRing(data.context_info);
            }
            break;
        
        case 'context_update':
            // 压缩后更新上下文使用量
            if (data.context_info) {
                updateContextRing(data.context_info);
            }
            break;
        
        case 'interrupted':
            // 用户中断了执行
            setSendButtonMode('send');
            stopPendingPreviewPolling();
            addSystemMessage('执行已被用户中断');
            // 刷新计划状态（中断后计划会被标记为 abandoned）
            loadPlan();
            break;
            
        case 'status':
        case 'sandbox_recreated':
            break;
    }
    scrollToBottom();
}

// 更新计划显示
function updatePlanDisplay(data) {
    const container = $('#plan-display');
    if (!container) return;
    
    // 保存当前计划数据
    state.currentPlan = data;
    
    const stateIcons = {
        'todo': '○',
        'pending': '○',
        'in_progress': '◐',
        'done': '✓',
        'failed': '✗',
        'abandoned': '⊘',
    };
    
    const stateLabels = {
        'todo': '待办',
        'pending': '待办',
        'in_progress': '进行中',
        'done': '已完成',
        'failed': '失败',
        'abandoned': '已跳过',
    };
    
    // 只读显示子任务
    const subtasksHtml = (data.subtasks || []).map((task, idx) => `
        <div class="subtask ${task.state}" data-idx="${idx}">
            <span class="subtask-icon">${stateIcons[task.state] || '○'}</span>
            <span class="subtask-name">${escapeHtml(task.name)}</span>
        </div>
    `).join('');
    
    // 只读显示计划（不可编辑）
    container.innerHTML = `
        <div class="plan-card">
            <div class="plan-header">
                <span class="plan-name">${escapeHtml(data.name || '任务计划')}</span>
                <span class="plan-state ${data.state}">${stateLabels[data.state] || '进行中'}</span>
            </div>
            <div class="subtasks">
                ${subtasksHtml || '<div class="empty-state">暂无子任务</div>'}
            </div>
        </div>
    `;
}

// 绑定计划编辑事件（内联编辑）
function bindPlanEditEvents() {
    const container = $('#plan-display');
    if (!container) return;
    
    // 计划名称内联编辑
    const planNameInput = container.querySelector('.plan-name-inline');
    if (planNameInput) {
        planNameInput.addEventListener('blur', () => savePlanInline());
        planNameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); savePlanInline(); planNameInput.blur(); }
        });
    }
    
    // 计划状态内联编辑
    const planStateSelect = container.querySelector('.plan-state-inline');
    if (planStateSelect) {
        planStateSelect.addEventListener('change', () => savePlanInline());
    }
    
    // 子任务名称内联编辑
    container.querySelectorAll('.subtask-name-inline').forEach(input => {
        input.addEventListener('blur', () => saveSubtaskInline(parseInt(input.dataset.idx)));
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); saveSubtaskInline(parseInt(input.dataset.idx)); input.blur(); }
        });
    });
    
    // 子任务状态内联编辑
    container.querySelectorAll('.subtask-state-inline').forEach(select => {
        select.addEventListener('change', () => saveSubtaskInline(parseInt(select.dataset.idx)));
    });
    
    // 添加子任务
    const newSubtaskInput = container.querySelector('.new-subtask-input');
    const addSubtaskBtn = container.querySelector('.add-subtask-btn');
    if (newSubtaskInput && addSubtaskBtn) {
        const addNewSubtask = async () => {
            const name = newSubtaskInput.value.trim();
            if (!name) return;
            await addSubtask({ name, state: 'todo' });
            newSubtaskInput.value = '';
        };
        addSubtaskBtn.addEventListener('click', addNewSubtask);
        newSubtaskInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); addNewSubtask(); }
        });
    }
    
    // 子任务删除按钮
    container.querySelectorAll('.subtask-delete-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            await deleteSubtask(parseInt(btn.dataset.idx));
        });
    });
}

// 保存计划内联编辑
async function savePlanInline() {
    const container = $('#plan-display');
    if (!container || !state.currentSession) return;
    
    const name = container.querySelector('.plan-name-inline')?.value.trim();
    const planState = container.querySelector('.plan-state-inline')?.value;
    
    if (!name) return;
    
    await updatePlan({ name, state: planState });
}

// 保存子任务内联编辑
async function saveSubtaskInline(idx) {
    const container = $('#plan-display');
    if (!container || !state.currentSession) return;
    
    const nameInput = container.querySelector(`.subtask-name-inline[data-idx="${idx}"]`);
    const stateSelect = container.querySelector(`.subtask-state-inline[data-idx="${idx}"]`);
    
    if (!nameInput) return;
    
    const name = nameInput.value.trim();
    const subtaskState = stateSelect?.value || 'todo';
    
    if (!name) return;
    
    await updateSubtask(idx, { name, state: subtaskState });
}

// 显示计划编辑弹窗
function showPlanEditModal() {
    const plan = state.currentPlan;
    if (!plan) return;
    
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal plan-edit-modal">
            <div class="modal-header">
                <h3>编辑计划</h3>
                <button class="modal-close">×</button>
            </div>
            <div class="modal-body">
                <label>计划名称</label>
                <input type="text" id="plan-name-input" value="${escapeHtml(plan.name || '')}" />
                <label>计划描述</label>
                <textarea id="plan-desc-input" rows="3">${escapeHtml(plan.description || '')}</textarea>
                <label>预期结果</label>
                <textarea id="plan-outcome-input" rows="3">${escapeHtml(plan.expected_outcome || '')}</textarea>
            </div>
            <div class="modal-footer">
                <button class="btn-cancel">取消</button>
                <button class="btn-save">保存</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    modal.querySelector('.modal-close').addEventListener('click', () => modal.remove());
    modal.querySelector('.btn-cancel').addEventListener('click', () => modal.remove());
    modal.querySelector('.btn-save').addEventListener('click', async () => {
        const name = document.getElementById('plan-name-input').value.trim();
        const description = document.getElementById('plan-desc-input').value.trim();
        const expected_outcome = document.getElementById('plan-outcome-input').value.trim();
        
        await updatePlan({ name, description, expected_outcome });
        modal.remove();
    });
}

// 显示子任务编辑弹窗
function showSubtaskEditModal(idx) {
    const isNew = idx < 0;
    const subtask = isNew ? { name: '', description: '', expected_outcome: '', state: 'todo' } 
                          : state.currentPlan.subtasks[idx];
    
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal subtask-edit-modal">
            <div class="modal-header">
                <h3>${isNew ? '添加子任务' : '编辑子任务'}</h3>
                <button class="modal-close">×</button>
            </div>
            <div class="modal-body">
                <label>子任务名称</label>
                <input type="text" id="subtask-name-input" value="${escapeHtml(subtask.name || '')}" />
                <label>描述</label>
                <textarea id="subtask-desc-input" rows="2">${escapeHtml(subtask.description || '')}</textarea>
                <label>预期结果</label>
                <textarea id="subtask-outcome-input" rows="2">${escapeHtml(subtask.expected_outcome || '')}</textarea>
                <label>状态</label>
                <select id="subtask-state-input">
                    <option value="todo" ${subtask.state === 'todo' ? 'selected' : ''}>待办</option>
                    <option value="in_progress" ${subtask.state === 'in_progress' ? 'selected' : ''}>进行中</option>
                    <option value="done" ${subtask.state === 'done' ? 'selected' : ''}>已完成</option>
                    <option value="failed" ${subtask.state === 'failed' ? 'selected' : ''}>失败</option>
                </select>
            </div>
            <div class="modal-footer">
                <button class="btn-cancel">取消</button>
                <button class="btn-save">保存</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    modal.querySelector('.modal-close').addEventListener('click', () => modal.remove());
    modal.querySelector('.btn-cancel').addEventListener('click', () => modal.remove());
    modal.querySelector('.btn-save').addEventListener('click', async () => {
        const data = {
            name: document.getElementById('subtask-name-input').value.trim(),
            description: document.getElementById('subtask-desc-input').value.trim(),
            expected_outcome: document.getElementById('subtask-outcome-input').value.trim(),
            state: document.getElementById('subtask-state-input').value,
        };
        
        if (isNew) {
            await addSubtask(data);
        } else {
            await updateSubtask(idx, data);
        }
        modal.remove();
    });
}

// API: 更新计划
async function updatePlan(data) {
    if (!state.currentSession) return;
    try {
        const resp = await fetch(`/api/plans/${state.currentSession}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${Api.token}` },
            body: JSON.stringify(data),
        });
        if (resp.ok) {
            const updated = await resp.json();
            updatePlanDisplay(updated);
        }
    } catch (err) {
        console.error('Update plan error:', err);
    }
}

// API: 更新子任务
async function updateSubtask(idx, data) {
    if (!state.currentSession) return;
    try {
        const resp = await fetch(`/api/plans/${state.currentSession}/subtasks/${idx}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${Api.token}` },
            body: JSON.stringify(data),
        });
        if (resp.ok) {
            // 重新加载计划
            await loadPlan();
        }
    } catch (err) {
        console.error('Update subtask error:', err);
    }
}

// API: 添加子任务
async function addSubtask(data) {
    if (!state.currentSession) return;
    try {
        const resp = await fetch(`/api/plans/${state.currentSession}/subtasks`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${Api.token}` },
            body: JSON.stringify(data),
        });
        if (resp.ok) {
            await loadPlan();
        }
    } catch (err) {
        console.error('Add subtask error:', err);
    }
}

// API: 删除子任务
async function deleteSubtask(idx) {
    if (!state.currentSession) return;
    try {
        const resp = await fetch(`/api/plans/${state.currentSession}/subtasks/${idx}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${Api.token}` },
        });
        if (resp.ok) {
            await loadPlan();
        }
    } catch (err) {
        console.error('Delete subtask error:', err);
    }
}

// API: 加载计划
async function loadPlan() {
    if (!state.currentSession) return;
    try {
        const resp = await fetch(`/api/plans/${state.currentSession}`, {
            headers: { 'Authorization': `Bearer ${Api.token}` },
        });
        if (resp.ok) {
            const plan = await resp.json();
            if (plan) {
                updatePlanDisplay(plan);
            }
        }
    } catch (err) {
        console.error('Load plan error:', err);
    }
}

// 切换到计划标签页
function switchToPlanTab() {
    $$('.sidebar-right .tab-btn').forEach(btn => btn.classList.remove('active'));
    $$('.sidebar-right .tab-content').forEach(tab => tab.classList.remove('active'));
    $('[data-tab="plan"]').classList.add('active');
    $('#tab-plan').classList.add('active');
}

// ==================== 计划预览确认功能 ====================

// 显示计划预览卡片（带倒计时）
// 始终在消息流中显示，不使用浮动定位
function showPlanPreview(data, timeoutSeconds = 180) {
    const { preview_id, name, subtasks } = data;  // 注意：不解构 state，避免覆盖全局 state
    
    // 防止重复显示同一个预览（检查相同 preview_id）
    if (document.getElementById(`plan-preview-${preview_id}`)) return;
    
    // 如果有旧的预览卡片，先移除（一个会话同时只显示一个计划预览）
    const existingCard = document.querySelector('.plan-preview-card');
    if (existingCard) {
        existingCard.remove();
        state.currentPendingPreviewId = null;  // 使用全局 state
    }
    
    // 记录当前预览 ID
    state.currentPendingPreviewId = preview_id;
    
    // 构建子任务列表HTML
    const subtasksHtml = subtasks.map((st, idx) => `
        <div class="plan-subtask-preview" data-idx="${idx}">
            <span class="subtask-state ${st.state}">${getStateIcon(st.state)}</span>
            <input type="text" class="subtask-name-input" value="${escapeHtml(st.name)}" />
            <button class="subtask-delete-btn" onclick="deletePlanPreviewSubtask('${preview_id}', ${idx})">×</button>
        </div>
    `).join('');
    
    // 创建预览卡片（始终在消息流中）
    const card = document.createElement('div');
    card.className = 'plan-preview-card';
    card.id = `plan-preview-${preview_id}`;
    card.dataset.previewId = preview_id;
    card.dataset.sessionId = state.currentSession;  // 绑定所属会话
    card.innerHTML = `
        <div class="plan-preview-header">
            <span class="plan-icon">📋</span>
            <span class="plan-title">计划预览</span>
            <span class="countdown" data-seconds="${timeoutSeconds}">⏱ ${formatCountdown(timeoutSeconds)}</span>
            <span class="plan-status pending">待确认</span>
        </div>
        <div class="plan-preview-body">
            <label>计划名称</label>
            <input type="text" class="plan-name-input" value="${escapeHtml(name)}" />
            <label>子任务列表</label>
            <div class="plan-subtasks-list">
                ${subtasksHtml}
            </div>
            <div class="add-subtask-row">
                <input type="text" class="new-subtask-input" placeholder="添加新子任务..." />
                <button class="add-subtask-btn" onclick="addPlanPreviewSubtask('${preview_id}')">+</button>
            </div>
        </div>
        <div class="plan-preview-actions">
            <button class="btn-cancel" onclick="cancelPlanPreview('${preview_id}')">✕ 取消对话</button>
            <button class="btn-run" onclick="confirmPlanPreview('${preview_id}')">✓ 确认执行</button>
        </div>
    `;
    
    // 始终插入消息流
    $('#messages').appendChild(card);
    scrollToBottom(true);
    
    // 自动切换到计划标签页
    switchToPlanTab();
    
    // 启动倒计时
    startPlanCountdown(preview_id, timeoutSeconds);
    
    // 编辑时重置倒计时
    card.querySelectorAll('input').forEach(input => {
        input.addEventListener('input', () => resetCountdown(preview_id, 180));
        input.addEventListener('focus', () => resetCountdown(preview_id, 180));
    });
}

// 获取状态图标
function getStateIcon(state) {
    switch(state) {
        case 'completed': return '✓';
        case 'in_progress': return '▶';
        case 'failed': return '✗';
        default: return '○';
    }
}

// 启动计划倒计时（仅设置初始显示，实际倒计时由后端轮询更新）
function startPlanCountdown(previewId, seconds) {
    const card = document.getElementById(`plan-preview-${previewId}`);
    if (!card) return;
    
    const countdownEl = card.querySelector('.countdown');
    if (!countdownEl) return;
    
    // 仅设置初始显示，后续由 loadPendingPreview 轮询从后端同步时间
    countdownEl.textContent = `⏱ ${formatCountdown(seconds)}`;
    countdownEl.dataset.seconds = seconds;
    
    if (seconds <= 30) {
        countdownEl.classList.add('warning');
    }
}

// 更新计划预览状态
function updatePlanPreviewStatus(previewId, status, autoConfirm) {
    const card = document.getElementById(`plan-preview-${previewId}`);
    if (!card) return;
    
    // 清除倒计时
    if (card.dataset.countdownTimer) {
        clearInterval(parseInt(card.dataset.countdownTimer));
    }
    
    // 确认后直接移除卡片，不再展示
    if (status === 'confirmed') {
        card.remove();
        state.currentPendingPreviewId = null;
        return;
    }
    
    // 取消状态保留短暂显示后移除
    if (status === 'cancelled') {
        const statusEl = card.querySelector('.plan-status');
        const actionsEl = card.querySelector('.plan-preview-actions');
        const countdownEl = card.querySelector('.countdown');
        if (countdownEl) countdownEl.remove();
        if (statusEl) {
            statusEl.className = 'plan-status cancelled';
            statusEl.textContent = '已取消';
        }
        if (actionsEl) actionsEl.remove();
        card.querySelectorAll('input').forEach(input => input.disabled = true);
        // 1秒后移除卡片
        setTimeout(() => card.remove(), 1000);
        state.currentPendingPreviewId = null;
    }
}

// 确认计划预览
async function confirmPlanPreview(previewId) {
    const card = document.getElementById(`plan-preview-${previewId}`);
    if (!card) return;
    
    // 获取用户可能编辑过的计划名称和子任务
    const planName = card.querySelector('.plan-name-input')?.value || '';
    const subtaskInputs = card.querySelectorAll('.subtask-name-input');
    const subtasks = Array.from(subtaskInputs).map(input => input.value).filter(s => s.trim());
    
    try {
        const resp = await fetch(`/api/kuncode/${state.currentSession}/plan/confirm/${previewId}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
            body: JSON.stringify({ 
                name: planName,
                subtasks: subtasks,
                action: 'confirm' 
            }),
        });
        
        if (resp.ok) {
            updatePlanPreviewStatus(previewId, 'confirmed', false);
        }
    } catch (err) {
        console.error('Confirm plan error:', err);
    }
}

// 取消计划预览（结束对话）
async function cancelPlanPreview(previewId) {
    // 立即移除预览卡片（不等待 API 响应）
    const card = document.getElementById(`plan-preview-${previewId}`);
    if (card) card.remove();
    
    // 立即断开流式连接
    disconnectCurrentStream();
    stopPendingPreviewPolling();
    state.currentPendingPreviewId = null;
    state.pendingPlanPreview = null;
    setSendButtonMode('send');
    
    try {
        // 调用后端中断 API 停止 AI 执行
        await fetch(`/api/conversation/session/${state.currentSession}/interrupt`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
        });
        
        // 取消确认（使用计划专用 API）
        await fetch(`/api/kuncode/${state.currentSession}/plan/confirm/${previewId}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
            body: JSON.stringify({ name: '', subtasks: [], action: 'cancel' }),
        });
    } catch (err) {
        console.error('Cancel plan error:', err);
    }
    
    addSystemMessage('执行已被用户中断');
}

// 在计划预览中添加子任务
function addPlanPreviewSubtask(previewId) {
    const card = document.getElementById(`plan-preview-${previewId}`);
    if (!card) return;
    
    const input = card.querySelector('.new-subtask-input');
    const name = input?.value.trim();
    if (!name) return;
    
    const list = card.querySelector('.plan-subtasks-list');
    const idx = list.querySelectorAll('.plan-subtask-preview').length;
    
    const newSubtask = document.createElement('div');
    newSubtask.className = 'plan-subtask-preview';
    newSubtask.dataset.idx = idx;
    newSubtask.innerHTML = `
        <span class="subtask-state todo">${getStateIcon('todo')}</span>
        <input type="text" class="subtask-name-input" value="${escapeHtml(name)}" />
        <button class="subtask-delete-btn" onclick="deletePlanPreviewSubtask('${previewId}', ${idx})">×</button>
    `;
    list.appendChild(newSubtask);
    input.value = '';
    
    // 重置倒计时
    resetCountdown(previewId, 180);
}

// 在计划预览中删除子任务
function deletePlanPreviewSubtask(previewId, idx) {
    const card = document.getElementById(`plan-preview-${previewId}`);
    if (!card) return;
    
    const subtask = card.querySelector(`.plan-subtask-preview[data-idx="${idx}"]`);
    if (subtask) subtask.remove();
    
    // 重新编号
    card.querySelectorAll('.plan-subtask-preview').forEach((el, i) => {
        el.dataset.idx = i;
        const deleteBtn = el.querySelector('.subtask-delete-btn');
        if (deleteBtn) {
            deleteBtn.onclick = () => deletePlanPreviewSubtask(previewId, i);
        }
    });
    
    // 重置倒计时
    resetCountdown(previewId, 180);
}

// ==================== Kuncode 预览确认功能 ====================

// 显示 Kuncode 预览卡片（带倒计时）
// 始终在消息流中显示
async function showKuncodePreview(data, timeoutSeconds = 180) {
    const { preview_id, prompt, agent, model } = data;
    
    // 防止重复显示同一个预览（检查相同 preview_id）
    if (document.getElementById(`kuncode-preview-${preview_id}`)) return;
    
    // 如果有旧的预览卡片，先移除（一个会话同时只显示一个 Kuncode 预览）
    const existingCard = document.querySelector('.kuncode-preview-card');
    if (existingCard) {
        existingCard.remove();
        state.currentPendingPreviewId = null;
    }
    
    // 获取可用的 Agent 列表
    let agentOptions = '';
    try {
        const agents = await Api.request('GET', '/sandbox/agents/names?mode=primary');
        agentOptions = agents.map(a => 
            `<option value="${escapeHtml(a.name)}" ${a.name === agent ? 'selected' : ''}>${escapeHtml(a.name)}</option>`
        ).join('');
    } catch (e) {
        agentOptions = `<option value="${escapeHtml(agent || '')}" selected>${escapeHtml(agent || 'root-cause-analyst')}</option>`;
    }
    
    // 创建预览卡片
    const card = document.createElement('div');
    card.className = 'kuncode-preview-card';
    card.id = `kuncode-preview-${preview_id}`;
    card.dataset.previewId = preview_id;
    card.dataset.sessionId = state.currentSession;  // 绑定所属会话
    card.innerHTML = `
        <div class="kuncode-preview-header">
            <span class="kuncode-icon">🤖</span>
            <span class="kuncode-title">KunCode 任务预览</span>
            <span class="countdown" data-seconds="${timeoutSeconds}">⏱ ${formatCountdown(timeoutSeconds)}</span>
            <span class="kuncode-status pending">待确认</span>
        </div>
        <div class="kuncode-preview-body">
            <label>任务描述（180秒后自动执行）</label>
            <textarea class="kuncode-prompt" rows="6">${escapeHtml(prompt)}</textarea>
            <div class="kuncode-meta">
                <label>Agent: <select class="kuncode-agent">${agentOptions}</select></label>
                ${model ? `<span>Model: ${escapeHtml(model)}</span>` : ''}
            </div>
        </div>
        <div class="kuncode-preview-actions">
            <button class="btn-cancel" onclick="cancelKuncode('${preview_id}')">✕ 取消</button>
            <button class="btn-run" onclick="confirmKuncode('${preview_id}')">▶ 执行</button>
        </div>
    `;
    
    // 始终插入消息流
    $('#messages').appendChild(card);
    scrollToBottom(true);
    
    // 启动倒计时
    startCountdown(preview_id, timeoutSeconds);
    
    // 编辑时重置倒计时
    const promptEl = card.querySelector('.kuncode-prompt');
    const agentEl = card.querySelector('.kuncode-agent');
    if (promptEl) {
        promptEl.addEventListener('input', () => resetCountdown(preview_id, 180));
        promptEl.addEventListener('focus', () => resetCountdown(preview_id, 180));
    }
    if (agentEl) {
        agentEl.addEventListener('change', () => resetCountdown(preview_id, 180));
        agentEl.addEventListener('focus', () => resetCountdown(preview_id, 180));
    }
}

// 重置倒计时（用户编辑时调用）
// 使用 Map 为每个 session 维护独立的防抖
const resetPreviewDebounceMap = new Map();
function resetCountdown(previewId, seconds) {
    // 查找卡片（支持多种前缀）
    let card = document.getElementById(`kuncode-preview-${previewId}`) 
            || document.getElementById(`plan-preview-${previewId}`)
            || document.getElementById(`user-input-request-${previewId}`);
    if (!card) return;
    
    // 获取卡片所属的 session_id（从 data 属性或当前会话）
    const sessionId = card.dataset.sessionId || state.currentSession;
    if (!sessionId) return;
    
    // 更新倒计时显示（临时显示，下次轮询会从后端同步）
    const countdownEl = card.querySelector('.countdown');
    if (countdownEl) {
        countdownEl.textContent = `⏱ ${formatCountdown(seconds)}`;
        countdownEl.dataset.seconds = seconds;
        countdownEl.classList.remove('warning', 'expired');
    }
    
    // 启用按钮（可能之前被禁用了）
    card.querySelectorAll('button').forEach(btn => btn.disabled = false);
    
    // 检查是否是计划预览卡片
    const isPlanPreview = card.classList.contains('plan-preview-card');
    
    // 为每个 session 维护独立的防抖，避免不同对话互相影响
    const debounceKey = `${sessionId}_${previewId}`;
    if (resetPreviewDebounceMap.has(debounceKey)) {
        clearTimeout(resetPreviewDebounceMap.get(debounceKey));
    }
    
    // 捕获当前 sessionId，防抖回调中使用
    const capturedSessionId = sessionId;
    resetPreviewDebounceMap.set(debounceKey, setTimeout(async () => {
        resetPreviewDebounceMap.delete(debounceKey);
        try {
            if (isPlanPreview) {
                // 计划预览：同时保存编辑内容
                await savePlanPreviewContent(previewId, capturedSessionId);
            } else {
                // 其他预览：只重置计时器
                await fetch(`/api/kuncode/${capturedSessionId}/preview/reset`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${Api.token}`,
                        'Content-Type': 'application/json',
                    },
                });
            }
        } catch (err) {
            console.error('Reset preview timer error:', err);
        }
    }, 1000));  // 1秒防抖
}

// 保存计划预览内容到后端
async function savePlanPreviewContent(previewId, sessionId) {
    const card = document.getElementById(`plan-preview-${previewId}`);
    // 使用传入的 sessionId，或从卡片获取，最后才用全局状态
    const targetSession = sessionId || card?.dataset.sessionId || state.currentSession;
    if (!card || !targetSession) return;
    
    // 获取当前编辑的内容
    const nameInput = card.querySelector('.plan-name-input');
    const name = nameInput?.value.trim() || '';
    
    const subtaskInputs = card.querySelectorAll('.plan-subtask-preview .subtask-name-input');
    const subtasks = Array.from(subtaskInputs).map(input => input.value.trim()).filter(s => s);
    
    try {
        await fetch(`/api/kuncode/${targetSession}/plan/update`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${Api.token}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name, subtasks }),
        });
    } catch (err) {
        console.error('Save plan preview content error:', err);
    }
}

// 启动倒计时（仅设置初始显示，实际倒计时由后端轮询更新）
function startCountdown(previewId, seconds) {
    const card = document.getElementById(`kuncode-preview-${previewId}`);
    if (!card) return;
    
    const countdownEl = card.querySelector('.countdown');
    if (!countdownEl) return;
    
    // 仅设置初始显示，后续由 loadPendingPreview 轮询从后端同步时间
    countdownEl.textContent = `⏱ ${formatCountdown(seconds)}`;
    countdownEl.dataset.seconds = seconds;
    
    if (seconds <= 30) {
        countdownEl.classList.add('warning');
    }
}

// 更新 Kuncode 预览卡片状态
function updateKuncodePreviewStatus(previewId, status, prompt) {
    const card = document.getElementById(`kuncode-preview-${previewId}`);
    if (!card) return;
    
    // 清除倒计时
    if (card.dataset.countdownTimer) {
        clearInterval(parseInt(card.dataset.countdownTimer));
    }
    
    // 确认后直接移除卡片
    if (status === 'executing') {
        card.remove();
        state.currentPendingPreviewId = null;
        return;
    }
    
    // 取消状态短暂显示后移除
    if (status === 'cancelled') {
        const statusEl = card.querySelector('.kuncode-status');
        const actionsEl = card.querySelector('.kuncode-preview-actions');
        const countdownEl = card.querySelector('.countdown');
        if (countdownEl) countdownEl.remove();
        if (statusEl) {
            statusEl.className = 'kuncode-status cancelled';
            statusEl.textContent = '已取消';
        }
        if (actionsEl) actionsEl.remove();
        const promptEl = card.querySelector('.kuncode-prompt');
        if (promptEl) promptEl.disabled = true;
        setTimeout(() => card.remove(), 1000);
        state.currentPendingPreviewId = null;
    }
}

// 确认执行 Kuncode
async function confirmKuncode(previewId) {
    const card = document.getElementById(`kuncode-preview-${previewId}`);
    if (!card) {
        console.warn('confirmKuncode: card not found for', previewId);
        return;
    }
    
    const promptEl = card.querySelector('.kuncode-prompt');
    const agentEl = card.querySelector('.kuncode-agent');
    const prompt = promptEl ? promptEl.value : '';
    const agent = agentEl ? agentEl.value : '';
    
    // 立即移除卡片，不等待 API 响应（提升用户体验）
    card.remove();
    state.currentPendingPreviewId = null;
    
    // 清除倒计时
    if (card.dataset.countdownTimer) {
        clearInterval(parseInt(card.dataset.countdownTimer));
    }
    
    try {
        const resp = await fetch(`/api/kuncode/${state.currentSession}/confirm/${previewId}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
            body: JSON.stringify({ prompt, agent, action: 'confirm' }),
        });
        
        if (!resp.ok) {
            console.error('Confirm kuncode failed:', resp.status);
        }
    } catch (err) {
        console.error('Confirm kuncode error:', err);
    }
}

// 取消 Kuncode（中断执行）
async function cancelKuncode(previewId) {
    // 立即移除预览卡片（不等待 API 响应）
    const card = document.getElementById(`kuncode-preview-${previewId}`);
    if (card) card.remove();
    
    // 立即断开流式连接
    disconnectCurrentStream();
    stopPendingPreviewPolling();
    state.currentPendingPreviewId = null;
    setSendButtonMode('send');
    
    try {
        // 调用后端中断 API 停止 AI 执行
        await fetch(`/api/conversation/session/${state.currentSession}/interrupt`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
        });
        
        // 取消确认
        await fetch(`/api/kuncode/${state.currentSession}/confirm/${previewId}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
            body: JSON.stringify({ prompt: '', action: 'cancel' }),
        });
    } catch (err) {
        console.error('Cancel kuncode error:', err);
    }
    
    addSystemMessage('执行已被用户中断');
}

// ==================== 用户输入请求功能 ====================

// 显示用户输入请求（带倒计时）
// 始终在消息流中显示
function showUserInputRequest(data, timeoutSeconds = 180) {
    const { request_id, message } = data;
    
    // 防止重复显示
    if (document.querySelector('.user-input-request-card')) return;
    
    // 保存当前请求ID
    state.pendingUserInputRequestId = request_id;
    
    // 创建输入请求卡片
    const card = document.createElement('div');
    card.className = 'user-input-request-card';
    card.id = `user-input-request-${request_id}`;
    card.dataset.previewId = request_id;
    card.dataset.sessionId = state.currentSession;  // 绑定所属会话
    card.innerHTML = `
        <div class="user-input-header">
            <span class="icon">💬</span>
            <span class="title">AI 正在等待您的输入</span>
            <span class="countdown" data-seconds="${timeoutSeconds}">⏱ ${formatCountdown(timeoutSeconds)}</span>
            <span class="status pending">等待中</span>
        </div>
        <div class="user-input-body">
            <label>3分钟后将自动跳过</label>
            <textarea class="user-input-text" rows="3" placeholder="请输入您的回答..."></textarea>
        </div>
        <div class="user-input-actions">
            <button class="btn-cancel" onclick="cancelUserInput('${request_id}')">跳过</button>
            <button class="btn-submit" onclick="submitUserInput('${request_id}')">提交</button>
        </div>
    `;
    
    // 始终插入消息流
    $('#messages').appendChild(card);
    scrollToBottom(true);
    
    // 绑定输入事件重置倒计时（不自动聚焦，让用户主动点击）
    const textarea = card.querySelector('.user-input-text');
    if (textarea) {
        // 编辑时重置倒计时
        textarea.addEventListener('input', () => resetCountdown(request_id, 180));
        textarea.addEventListener('focus', () => resetCountdown(request_id, 180));
    }
    
    // 启动倒计时（复用kuncode的倒计时函数，使用request_id作为previewId）
    startUserInputCountdown(request_id, timeoutSeconds);
}

// 启动用户输入倒计时（仅设置初始显示，实际倒计时由后端轮询更新）
function startUserInputCountdown(requestId, seconds) {
    const card = document.getElementById(`user-input-request-${requestId}`);
    if (!card) return;
    
    const countdownEl = card.querySelector('.countdown');
    if (!countdownEl) return;
    
    // 仅设置初始显示，后续由 loadPendingPreview 轮询从后端同步时间
    countdownEl.textContent = `⏱ ${formatCountdown(seconds)}`;
    countdownEl.dataset.seconds = seconds;
    
    if (seconds <= 30) {
        countdownEl.classList.add('warning');
    }
}

// 更新用户输入状态
function updateUserInputStatus(requestId, status, content) {
    const card = document.getElementById(`user-input-request-${requestId}`);
    if (!card) return;
    
    // 清除倒计时
    if (card.dataset.countdownTimer) {
        clearInterval(parseInt(card.dataset.countdownTimer));
    }
    const countdownEl = card.querySelector('.countdown');
    if (countdownEl) countdownEl.remove();
    
    const statusEl = card.querySelector('.status');
    const actionsEl = card.querySelector('.user-input-actions');
    const textareaEl = card.querySelector('.user-input-text');
    
    if (status === 'received') {
        if (statusEl) {
            statusEl.className = 'status completed';
            statusEl.textContent = '已提交';
        }
        if (actionsEl) actionsEl.remove();
        if (textareaEl) {
            textareaEl.disabled = true;
            if (content) textareaEl.value = content;
        }
    } else if (status === 'cancelled') {
        if (statusEl) {
            statusEl.className = 'status cancelled';
            statusEl.textContent = '已跳过';
        }
        if (actionsEl) actionsEl.remove();
        if (textareaEl) textareaEl.disabled = true;
        // 短暂显示后移除卡片
        setTimeout(() => card.remove(), 1000);
    }
    
    state.pendingUserInputRequestId = null;
}

// 提交用户输入
async function submitUserInput(requestId) {
    const card = document.getElementById(`user-input-request-${requestId}`);
    if (!card) return;
        
    const textarea = card.querySelector('.user-input-text');
    const content = textarea ? textarea.value.trim() : '';
        
    if (!content) {
        alert('请输入内容');
        return;
    }
        
    try {
        const resp = await fetch(`/api/kuncode/${state.currentSession}/confirm/${requestId}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
            body: JSON.stringify({ prompt: content, action: 'confirm' }),
        });
            
        if (resp.ok) {
            updateUserInputStatus(requestId, 'received', content);
        }
    } catch (err) {
        console.error('Submit user input error:', err);
    }
}

// 跳过用户输入（不中断AI，让AI继续执行）
async function cancelUserInput(requestId) {
    // 更新卡片状态
    updateUserInputStatus(requestId, 'cancelled', '');
    state.pendingUserInputRequestId = null;
    
    try {
        // 发送跳过确认（不调用 interrupt API，让 AI 继续执行）
        await fetch(`/api/kuncode/${state.currentSession}/confirm/${requestId}`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${Api.token}` 
            },
            body: JSON.stringify({ prompt: '', action: 'cancel' }),
        });
    } catch (err) {
        console.error('Skip user input error:', err);
    }
}

// 从历史记录渲染 Kuncode 预览卡片
function renderKuncodePreviewFromHistory(container, data) {
    const { preview_id, prompt, confirmed_prompt, status, agent, model } = data;
    
    // 确定显示的 prompt（如果已确认且有编辑，显示编辑后的）
    const displayPrompt = confirmed_prompt || prompt;
    
    // 确定状态显示
    let statusClass = status || 'completed';
    let statusText = '已完成';
    if (status === 'pending') {
        statusText = '待确认';
        statusClass = 'pending';
    } else if (status === 'cancelled') {
        statusText = '已取消';
        statusClass = 'cancelled';
    } else if (status === 'confirmed' || status === 'executed') {
        statusText = '已执行';
        statusClass = 'completed';
    }
    
    const card = document.createElement('div');
    card.className = 'kuncode-preview-card';
    card.id = `kuncode-preview-${preview_id}`;
    card.innerHTML = `
        <div class="kuncode-preview-header">
            <span class="kuncode-icon">🤖</span>
            <span class="kuncode-title">KunCode 任务</span>
            <span class="kuncode-status ${statusClass}">${statusText}</span>
        </div>
        <div class="kuncode-preview-body">
            <label>任务描述${confirmed_prompt && confirmed_prompt !== prompt ? ' (已编辑)' : ''}</label>
            <textarea class="kuncode-prompt" rows="4" disabled>${escapeHtml(displayPrompt)}</textarea>
            <div class="kuncode-meta">
                ${agent ? `<span>Agent: ${escapeHtml(agent)}</span>` : ''}
                ${model ? `<span>Model: ${escapeHtml(model)}</span>` : ''}
            </div>
        </div>
    `;
    
    container.appendChild(card);
}

// 清空右侧面板状态（切换会话时调用）
function clearRightPanelState() {
    // 清空计划
    const planDisplay = $('#plan-display');
    if (planDisplay) {
        planDisplay.innerHTML = '<div class="empty-state">暂无计划</div>';
    }
    
    // 清空终端并显示默认提示符
    const terminalBody = $('#terminal-body');
    if (terminalBody) {
        terminalBody.innerHTML = '';
        addDefaultTerminalPrompt();
    }
    
    // 重置文件浏览状态
    state.currentPath = '';
    state.viewingFile = null;
    $('#sandbox-files-container').classList.remove('hidden');
    $('#file-content-view').classList.add('hidden');
}

// 添加默认终端提示符
function addDefaultTerminalPrompt() {
    const terminal = $('#terminal-body');
    const promptLine = document.createElement('div');
    promptLine.className = 'terminal-line terminal-prompt-line';
    promptLine.innerHTML = `<span class="prompt"><span class="user">phantom</span><span class="at">@</span><span class="host">agent_sandbox</span>:~$ </span>`;
    terminal.appendChild(promptLine);
}

// 解析工具输入为命令字符串
function parseToolCommand(toolName, inputStr) {
    let cmd = toolName;
    let isMultiLine = false;
    try {
        const args = typeof inputStr === 'string' ? JSON.parse(inputStr) : inputStr;
        if (toolName === 'run_shell_command' && args?.command) {
            cmd = args.command;
            isMultiLine = cmd.includes('\n');
        } else if (toolName === 'run_ipython_cell' && args?.code) {
            // 显示完整代码，保留换行
            cmd = `python -c "\n${args.code}`;
            isMultiLine = true;
        } else if (toolName === 'run_kuncode') {
            if (args?.prompt) {
                cmd = `kuncode run "${args.prompt.substring(0, 200)}${args.prompt.length > 200 ? '...' : ''}"`;
            } else {
                cmd = 'kuncode run ...';
            }
        }
    } catch (e) {}
    return { cmd, isMultiLine };
}

// 添加终端命令行
function addTerminalCommand(toolName, inputStr, toolId) {
    const terminal = $('#terminal-body');
    
    // 检查是否已有此命令（防止重复）
    if ($(`#term-cmd-${toolId}`)) {
        return; // 已存在，跳过
    }
    
    const { cmd, isMultiLine } = parseToolCommand(toolName, inputStr);
    
    // 移除默认提示符行和最终提示符行（如果存在）
    const defaultPrompt = terminal.querySelector('.terminal-prompt-line');
    if (defaultPrompt) defaultPrompt.remove();
    const finalPrompt = terminal.querySelector('.terminal-prompt-final');
    if (finalPrompt) finalPrompt.remove();
    
    const line = document.createElement('div');
    line.className = 'terminal-line' + (isMultiLine ? ' multi-line-cmd' : '');
    line.id = `term-cmd-${toolId}`;
    line.dataset.callId = toolId;  // 添加 data-call-id 用于点击定位
    // 多行命令使用 <pre> 保留格式
    const cmdHtml = isMultiLine 
        ? `<pre class="cmd-block">${escapeHtml(cmd)}</pre>`
        : `<span class="cmd">${escapeHtml(cmd)}</span>`;
    line.innerHTML = `<span class="prompt"><span class="user">phantom</span><span class="at">@</span><span class="host">agent_sandbox</span>:~$ </span>${cmdHtml}`;
    terminal.appendChild(line);
    
    // 创建输出行
    const outLine = document.createElement('div');
    outLine.className = 'terminal-line terminal-output running';
    outLine.id = `term-out-${toolId}`;
    outLine.dataset.callId = toolId;  // 添加 data-call-id 用于点击定位
    outLine.innerHTML = '<span class="output"><span class="terminal-running">running...</span></span>';
    terminal.appendChild(outLine);
    
    scrollTerminalToBottom();
}

// 更新终端命令（当input变化时）
function updateTerminalCommand(toolId, toolName, inputStr) {
    const cmdLine = $(`#term-cmd-${toolId}`);
    if (cmdLine) {
        const { cmd, isMultiLine } = parseToolCommand(toolName, inputStr);
        // 更新命令内容
        let cmdEl = cmdLine.querySelector('.cmd-block') || cmdLine.querySelector('.cmd');
        if (isMultiLine && !cmdLine.querySelector('.cmd-block')) {
            // 需要切换到多行模式
            cmdLine.classList.add('multi-line-cmd');
            const oldCmd = cmdLine.querySelector('.cmd');
            if (oldCmd) {
                const pre = document.createElement('pre');
                pre.className = 'cmd-block';
                pre.textContent = cmd;
                oldCmd.replaceWith(pre);
            }
        } else if (cmdEl) {
            cmdEl.textContent = cmd;
        }
    }
}

// 更新终端输出（流式）- 使用当前 state 中的 toolId
function updateTerminalOutput(content) {
    updateTerminalOutputById(state.stream.currentToolId, content);
}

// 更新终端输出（流式）- 使用指定的 toolId
function updateTerminalOutputById(toolId, content) {
    const terminal = $('#terminal-body');
    if (!terminal) return;
    
    // 流式更新时移除最终提示符（等流结束再添加）
    const finalPrompt = terminal.querySelector('.terminal-prompt-final');
    if (finalPrompt) finalPrompt.remove();
    
    let outLine = toolId ? $(`#term-out-${toolId}`) : null;
    
    // 如果输出行不存在，创建一个（断点续传场景）
    if (!outLine && toolId) {
        // 尝试找到对应的命令行，在其后插入输出行
        const cmdLine = $(`#term-cmd-${toolId}`) || $(`[data-call-id="${toolId}"]`);
        if (cmdLine) {
            outLine = document.createElement('div');
            outLine.className = 'terminal-line terminal-output running';
            outLine.id = `term-out-${toolId}`;
            outLine.dataset.callId = toolId;
            outLine.innerHTML = '<span class="output"><span class="terminal-running">running...</span></span>';
            // 插入到命令行后面
            cmdLine.after(outLine);
        }
        // 如果命令行不存在，不创建孤立的输出行（避免空白行问题）
    }
    
    if (outLine) {
        outLine.classList.remove('running');
        const outputEl = outLine.querySelector('.output');
        // 去掉末尾的退出码，使用ANSI颜色解析
        const cleanContent = content.replace(/\n\d+$/, '');
        if (outputEl) outputEl.innerHTML = parseAnsiToHtml(cleanContent);
    }
    scrollTerminalToBottom();
}

function markSandboxToolFinished(toolId, content = '') {
    if (!toolId) return;
    const failed = typeof content === 'string' && /\[ERROR\]|traceback|failed|error:/i.test(content);
    const indicator = $(`.sandbox-tool-indicator[data-tool-id="${toolId}"]`) ||
                      $(`.sandbox-tool-indicator[data-call-id="${toolId}"]`);
    if (indicator) {
        indicator.classList.remove('running');
        indicator.classList.add(failed ? 'failed' : 'completed');
        const icon = indicator.querySelector('.icon');
        const status = indicator.querySelector('.status');
        if (icon) icon.textContent = failed ? '✕' : '✓';
        if (status) status.textContent = failed ? '失败' : '完成';
    }

    const outLine = $(`#term-out-${toolId}`);
    if (outLine) {
        outLine.classList.remove('running');
        outLine.classList.add(failed ? 'failed' : 'completed');
    }
}

function finalizeRunningSandboxTools() {
    $$('.sandbox-tool-indicator.running').forEach(indicator => {
        const toolId = indicator.dataset.toolId || indicator.dataset.callId;
        markSandboxToolFinished(toolId, '');
    });
    $$('.terminal-output.running').forEach(line => {
        line.classList.remove('running');
        line.classList.add('completed');
    });
}

// 切换到工具调用tab
function switchToToolsTab() {
    $$('.sidebar-right .tabs .tab-btn').forEach(b => b.classList.remove('active'));
    const toolsBtn = $('.sidebar-right .tabs .tab-btn[data-tab="tools"]');
    if (toolsBtn) toolsBtn.classList.add('active');
    $$('.sidebar-right .tab-content').forEach(c => c.classList.remove('active'));
    const toolsTab = $('#tab-tools');
    if (toolsTab) toolsTab.classList.add('active');
}

// Add user message with files
function addUserMessage(message, files = []) {
    const container = $('#messages');
    const group = document.createElement('div');
    group.className = 'msg-group user';
    
    // Files above message
    if (files.length > 0) {
        const filesDiv = document.createElement('div');
        filesDiv.className = 'msg-files';
        filesDiv.innerHTML = files.map(f => `
            <div class="msg-file">
                <div class="file-icon">${getFileIcon(f.original_name || f.filename)}</div>
                <div class="file-info">
                    <span class="file-name">${escapeHtml(f.original_name || f.filename)}</span>
                    <span class="file-size">${formatFileSize(f.size)}</span>
                </div>
            </div>
        `).join('');
        group.appendChild(filesDiv);
    }
    
    const msgEl = document.createElement('div');
    msgEl.className = 'message user';
    msgEl.textContent = message;
    group.appendChild(msgEl);
    
    container.appendChild(group);
    forceScrollToBottom();
}

// Add status message
function addStatusMessage(text) {
    const container = $('#messages');
    const el = document.createElement('div');
    el.className = 'message status loading';
    el.textContent = text;
    container.appendChild(el);
    return el;
}

// Add system message (non-loading)
function addSystemMessage(text) {
    const container = $('#messages');
    const el = document.createElement('div');
    el.className = 'message status';
    el.style.backgroundColor = '#fef3c7';
    el.style.color = '#92400e';
    el.textContent = text;
    container.appendChild(el);
    scrollToBottom();
    scrollToBottom();
    return el;
}

// Add error message
function addErrorMessage(text) {
    const container = $('#messages');
    const el = document.createElement('div');
    el.className = 'message error';
    el.textContent = text;
    container.appendChild(el);
    scrollToBottom();
}

// 记录用户是否在底部附近
let userNearBottom = true;

// 监听消息容器滚动事件
document.addEventListener('DOMContentLoaded', () => {
    const container = $('#messages');
    if (container) {
        container.addEventListener('scroll', () => {
            // 判断是否在底部附近（距离底部100px以内）
            const threshold = 100;
            userNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < threshold;
        });
    }
});

function scrollToBottom() {
    const container = $('#messages');
    // 只在用户在底部附近时自动滚动
    if (userNearBottom) {
        container.scrollTop = container.scrollHeight;
    }
}

// 强制滚动到底部（用于用户主动发送消息等场景）
function forceScrollToBottom() {
    const container = $('#messages');
    container.scrollTop = container.scrollHeight;
    userNearBottom = true;
}

// 管理后台页面切换
function showAdminPage() {
    $('#app-page').classList.add('hidden');
    $('#admin-page').classList.remove('hidden');
    loadKnowledgeList();
}

function showAppPage() {
    $('#admin-page').classList.add('hidden');
    $('#app-page').classList.remove('hidden');
}

// Knowledge 分页状态
const knowledgePagination = {
    currentPage: 1,
    pageSize: 10,
    total: 0
};

async function loadKnowledgeList(page = 1) {
    const category = $('#category-filter').value;
    const searchText = $('#knowledge-search')?.value?.trim() || '';
    knowledgePagination.currentPage = page;
    
    try {
        const res = await Api.listKnowledge(category || null, 500, 0); // 获取全部用于前端分页
        let items = res.items || [];
        
        // 搜索过滤
        if (searchText) {
            const lower = searchText.toLowerCase();
            items = items.filter(item => 
                item.title.toLowerCase().includes(lower) || 
                item.content.toLowerCase().includes(lower)
            );
        }
        
        // Update categories
        (res.items || []).forEach(item => {
            if (item.category) state.categories.add(item.category);
        });
        updateCategoryFilter();

        const container = $('#knowledge-list');
        if (items.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无知识条目</div>';
            return;
        }

        // 分页计算
        knowledgePagination.total = items.length;
        const totalPages = Math.ceil(items.length / knowledgePagination.pageSize);
        const startIdx = (page - 1) * knowledgePagination.pageSize;
        const endIdx = startIdx + knowledgePagination.pageSize;
        const pageItems = items.slice(startIdx, endIdx);

        // 渲染表格
        container.innerHTML = `
            <table class="knowledge-table">
                <thead>
                    <tr>
                        <th>标题</th>
                        <th>类别</th>
                        <th>内容预览</th>
                        <th>操作</th>
                    </tr>
                </thead>
                <tbody>
                    ${pageItems.map(item => `
                        <tr data-id="${item.id}">
                            <td><strong>${escapeHtml(item.title)}</strong></td>
                            <td><span class="category-badge">${escapeHtml(item.category || '未分类')}</span></td>
                            <td><div class="knowledge-content-preview">${escapeHtml(item.content.slice(0, 100))}...</div></td>
                            <td class="actions">
                                <button class="btn-edit" data-id="${item.id}">编辑</button>
                                <button class="btn-delete" data-id="${item.id}">删除</button>
                            </td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            ${renderPagination(page, totalPages, items.length)}
        `;

        container.querySelectorAll('.btn-edit').forEach(btn => {
            btn.addEventListener('click', () => editKnowledge(btn.dataset.id));
        });

        container.querySelectorAll('.btn-delete').forEach(btn => {
            btn.addEventListener('click', async () => {
                if (confirm('确定删除这条知识？')) {
                    await Api.deleteKnowledge(btn.dataset.id);
                    loadKnowledgeList(knowledgePagination.currentPage);
                }
            });
        });

        // 绑定分页事件
        container.querySelectorAll('.pagination-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const targetPage = parseInt(btn.dataset.page);
                if (targetPage && targetPage !== page) {
                    loadKnowledgeList(targetPage);
                }
            });
        });

    } catch (err) {
        $('#knowledge-list').innerHTML = '<div class="empty-state">加载失败: ' + err.message + '</div>';
    }
}

// 渲染分页控件
function renderPagination(currentPage, totalPages, totalItems) {
    if (totalPages <= 1) return '';
    
    let pages = [];
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    
    if (endPage - startPage < maxVisible - 1) {
        startPage = Math.max(1, endPage - maxVisible + 1);
    }
    
    // 上一页
    pages.push(`<button class="pagination-btn ${currentPage === 1 ? 'disabled' : ''}" data-page="${currentPage - 1}" ${currentPage === 1 ? 'disabled' : ''}>‹</button>`);
    
    // 首页
    if (startPage > 1) {
        pages.push(`<button class="pagination-btn" data-page="1">1</button>`);
        if (startPage > 2) pages.push(`<span class="pagination-ellipsis">...</span>`);
    }
    
    // 页码
    for (let i = startPage; i <= endPage; i++) {
        pages.push(`<button class="pagination-btn ${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`);
    }
    
    // 末页
    if (endPage < totalPages) {
        if (endPage < totalPages - 1) pages.push(`<span class="pagination-ellipsis">...</span>`);
        pages.push(`<button class="pagination-btn" data-page="${totalPages}">${totalPages}</button>`);
    }
    
    // 下一页
    pages.push(`<button class="pagination-btn ${currentPage === totalPages ? 'disabled' : ''}" data-page="${currentPage + 1}" ${currentPage === totalPages ? 'disabled' : ''}>›</button>`);
    
    return `
        <div class="pagination">
            <span class="pagination-info">共 ${totalItems} 条，第 ${currentPage}/${totalPages} 页</span>
            <div class="pagination-buttons">${pages.join('')}</div>
        </div>
    `;
}

function updateCategoryFilter() {
    const select = $('#category-filter');
    const current = select.value;
    select.innerHTML = '<option value="">全部类别</option>';
    state.categories.forEach(cat => {
        select.innerHTML += `<option value="${escapeHtml(cat)}">${escapeHtml(cat)}</option>`;
    });
    select.value = current;
}

function openKnowledgeEditModal(item = null) {
    $('#knowledge-edit-title').textContent = item ? '编辑知识' : '添加知识';
    $('#knowledge-id').value = item?.id || '';
    $('#knowledge-title').value = item?.title || '';
    $('#knowledge-category').value = item?.category || '';
    $('#knowledge-content').value = item?.content || '';
    
    // 重置编辑器标签页状态
    $$('.editor-tab').forEach(tab => tab.classList.remove('active'));
    $('.editor-tab[data-tab="edit"]').classList.add('active');
    $('#knowledge-content').classList.remove('hidden');
    $('#knowledge-preview').classList.add('hidden');
    
    $('#knowledge-edit-modal').classList.remove('hidden');
}

// 知识编辑器标签页切换
function initKnowledgeEditorTabs() {
    $$('.editor-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            $$('.editor-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            if (tabName === 'edit') {
                $('#knowledge-content').classList.remove('hidden');
                $('#knowledge-preview').classList.add('hidden');
            } else {
                // 预览模式：渲染 Markdown
                const content = $('#knowledge-content').value;
                $('#knowledge-preview').innerHTML = renderMarkdown(content);
                $('#knowledge-content').classList.add('hidden');
                $('#knowledge-preview').classList.remove('hidden');
            }
        });
    });
}

async function editKnowledge(id) {
    try {
        const res = await Api.listKnowledge();
        const item = res.items.find(i => i.id === id);
        if (item) openKnowledgeEditModal(item);
    } catch (err) {
        console.error('Load knowledge error:', err);
    }
}

async function saveKnowledge() {
    const id = $('#knowledge-id').value;
    const data = {
        title: $('#knowledge-title').value.trim(),
        category: $('#knowledge-category').value.trim() || null,
        content: $('#knowledge-content').value.trim()
    };

    try {
        if (id) {
            await Api.updateKnowledge(id, data);
        } else {
            await Api.createKnowledge(data);
        }
        $('#knowledge-edit-modal').classList.add('hidden');
        loadKnowledgeList();
    } catch (err) {
        alert('保存失败: ' + err.message);
    }
}

// 系统提示词管理
let promptSaveTimer = null;

async function loadSystemPrompt() {
    try {
        const res = await Api.getSystemPrompt();
        $('#system-prompt-editor').value = res.content || '';
        updatePromptPreview();
        if (res.updated_at) {
            showSaveStatus('saved', `上次保存: ${new Date(res.updated_at).toLocaleString()}`);
        }
    } catch (err) {
        console.error('Load system prompt error:', err);
        showSaveStatus('error', '加载失败');
    }
}

function initPromptEditor() {
    const editor = $('#system-prompt-editor');
    const preview = $('#system-prompt-preview');
    if (!editor || !preview) return;
    
    // 实时预览 + 自动保存
    editor.addEventListener('input', () => {
        updatePromptPreview();
        debounceSavePrompt();
    });
    
    // 同步滚动
    let isSyncingScroll = false;
    
    editor.addEventListener('scroll', () => {
        if (isSyncingScroll) return;
        isSyncingScroll = true;
        const scrollRatio = editor.scrollTop / (editor.scrollHeight - editor.clientHeight || 1);
        preview.scrollTop = scrollRatio * (preview.scrollHeight - preview.clientHeight);
        setTimeout(() => isSyncingScroll = false, 10);
    });
    
    preview.addEventListener('scroll', () => {
        if (isSyncingScroll) return;
        isSyncingScroll = true;
        const scrollRatio = preview.scrollTop / (preview.scrollHeight - preview.clientHeight || 1);
        editor.scrollTop = scrollRatio * (editor.scrollHeight - editor.clientHeight);
        setTimeout(() => isSyncingScroll = false, 10);
    });
}

function updatePromptPreview() {
    const content = $('#system-prompt-editor').value;
    $('#system-prompt-preview').innerHTML = renderMarkdown(content);
}

function debounceSavePrompt() {
    showSaveStatus('saving', '保存中...');
    
    if (promptSaveTimer) {
        clearTimeout(promptSaveTimer);
    }
    
    promptSaveTimer = setTimeout(async () => {
        try {
            const content = $('#system-prompt-editor').value;
            const res = await Api.updateSystemPrompt(content);
            showSaveStatus('saved', '已保存');
        } catch (err) {
            console.error('Save prompt error:', err);
            showSaveStatus('error', '保存失败: ' + err.message);
        }
    }, 1000); // 1秒防抖
}

function showSaveStatus(type, text) {
    const status = $('#prompt-save-status');
    if (!status) return;
    status.className = 'save-status ' + type;
    status.textContent = text;
}

// Utils
function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// CSV 解析并渲染为表格
function renderCsvAsTable(content, maxRows = 500) {
    const lines = content.split('\n').filter(line => line.trim());
    if (lines.length === 0) return '<p>空文件</p>';
    
    // 简单 CSV 解析（处理逗号分隔，支持引号内逗号）
    const parseRow = (line) => {
        const result = [];
        let current = '';
        let inQuotes = false;
        for (let i = 0; i < line.length; i++) {
            const char = line[i];
            if (char === '"') {
                inQuotes = !inQuotes;
            } else if (char === ',' && !inQuotes) {
                result.push(current.trim());
                current = '';
            } else {
                current += char;
            }
        }
        result.push(current.trim());
        return result;
    };
    
    const headers = parseRow(lines[0]);
    const rows = lines.slice(1, maxRows + 1).map(parseRow);
    
    let html = '<table class="csv-table"><thead><tr>';
    headers.forEach(h => html += `<th title="${escapeHtml(h)}">${escapeHtml(h)}</th>`);
    html += '</tr></thead><tbody>';
    
    rows.forEach(row => {
        html += '<tr>';
        row.forEach(cell => html += `<td title="${escapeHtml(cell)}">${escapeHtml(cell)}</td>`);
        html += '</tr>';
    });
    
    html += '</tbody></table>';
    
    if (lines.length > maxRows + 1) {
        html += `<p style="padding: 10px; color: #666; text-align: center;">显示前 ${maxRows} 行，共 ${lines.length - 1} 行</p>`;
    }
    
    return html;
}

function parseAnsiToHtml(text) {
    // ANSI颜色映射
    const ansiColors = {
        '30': 'color: #000',
        '31': 'color: #c41a16',  // 红色
        '32': 'color: #2fb41d',  // 绿色
        '33': 'color: #c4a000',  // 黄色
        '34': 'color: #3465a4',  // 蓝色
        '35': 'color: #75507b',  // 品红
        '36': 'color: #06989a',  // 青色
        '37': 'color: #d3d7cf',  // 白色
        '90': 'color: #888',     // 亮黑（灰）
        '91': 'color: #ef2929',  // 亮红
        '92': 'color: #8ae234',  // 亮绿
        '93': 'color: #fce94f',  // 亮黄
        '94': 'color: #729fcf',  // 亮蓝
        '95': 'color: #ad7fa8',  // 亮品红
        '96': 'color: #34e2e2',  // 亮青
        '97': 'color: #fff',     // 亮白
        '1': 'font-weight: bold',
        '0': ''  // 重置
    };
    
    // 先转义HTML
    let escaped = escapeHtml(text);
    
    // 解析ANSI序列: \x1b[XXm 或 \u001b[XXm
    // 匹配模式: ESC [ (数字;)* 数字 m
    const ansiRegex = /\x1b\[([0-9;]+)m/g;
    
    let result = '';
    let lastIndex = 0;
    let openSpans = 0;
    let match;
    
    while ((match = ansiRegex.exec(escaped)) !== null) {
        // 添加匹配前的文本
        result += escaped.substring(lastIndex, match.index);
        lastIndex = match.index + match[0].length;
        
        const codes = match[1].split(';');
        for (const code of codes) {
            if (code === '0') {
                // 重置：关闭所有打开的span
                while (openSpans > 0) {
                    result += '</span>';
                    openSpans--;
                }
            } else if (ansiColors[code]) {
                result += `<span style="${ansiColors[code]}">`;
                openSpans++;
            }
        }
    }
    
    // 添加剩余文本
    result += escaped.substring(lastIndex);
    
    // 关闭所有未关闭的span
    while (openSpans > 0) {
        result += '</span>';
        openSpans--;
    }
    
    return result;
}

function formatFileSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function getFileIcon(filename) {
    if (!filename) return '<span class="file-ext">FILE</span>';
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        // 代码
        py: 'PY', js: 'JS', ts: 'TS', jsx: 'JSX', tsx: 'TSX',
        html: 'HTML', css: 'CSS', sql: 'SQL',
        java: 'JAVA', c: 'C', cpp: 'CPP', go: 'GO', rs: 'RS',
        sh: 'SH', bash: 'SH', rb: 'RB', php: 'PHP',
        // 数据
        json: 'JSON', yaml: 'YML', yml: 'YML', xml: 'XML',
        csv: 'CSV', xlsx: 'XLS', xls: 'XLS',
        // 文档
        pdf: 'PDF', doc: 'DOC', docx: 'DOC',
        ppt: 'PPT', pptx: 'PPT',
        txt: 'TXT', md: 'MD', log: 'LOG',
        // 图片
        png: 'IMG', jpg: 'IMG', jpeg: 'IMG', gif: 'GIF', svg: 'SVG', webp: 'IMG',
        // 压缩
        zip: 'ZIP', tar: 'TAR', gz: 'GZ', rar: 'RAR', '7z': '7Z',
        // 配置
        ini: 'INI', cfg: 'CFG', conf: 'CONF', env: 'ENV',
        // 其他
        lock: 'LOCK', toml: 'TOML',
    };
    const label = icons[ext] || ext.toUpperCase().substring(0, 4);
    return `<span class="file-ext">${label}</span>`;
}

// ==================== 沙箱管理 ====================
let sandboxAgents = [];
let sandboxSkills = [];
let sandboxMcps = [];

function initSandboxManagement() {
    // 子标签页切换
    $$('.sandbox-nav-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const subtab = btn.dataset.subtab;
            $$('.sandbox-nav-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            $$('.sandbox-subtab-content').forEach(c => c.classList.remove('active'));
            $(`#sandbox-subtab-${subtab}`).classList.add('active');
        });
    });
    
    // Agent 管理
    $('#add-agent-btn')?.addEventListener('click', () => openAgentModal());
    $('#agent-save-btn')?.addEventListener('click', saveAgent);
    $('#agent-cancel-btn')?.addEventListener('click', () => $('#agent-edit-modal').classList.add('hidden'));
    $('#agent-edit-modal .close-btn')?.addEventListener('click', () => $('#agent-edit-modal').classList.add('hidden'));
    initAgentContentEditor();
    
    // Skill 管理
    $('#add-skill-btn')?.addEventListener('click', openSkillUploadModal);
    $('#skill-upload-cancel')?.addEventListener('click', () => $('#skill-upload-modal').classList.add('hidden'));
    $('#skill-perm-cancel')?.addEventListener('click', () => $('#skill-perm-modal').classList.add('hidden'));
    $('#skill-perm-save')?.addEventListener('click', saveSkillPermissions);
    $('#skill-detail-close')?.addEventListener('click', () => $('#skill-detail-modal').classList.add('hidden'));
    $('#skill-detail-modal .close-btn')?.addEventListener('click', () => $('#skill-detail-modal').classList.add('hidden'));
    initSkillUpload();
    
    // MCP 管理
    $('#add-mcp-btn')?.addEventListener('click', () => openMcpModal());
    $('#mcp-save-btn')?.addEventListener('click', saveMcp);
    $('#mcp-cancel-btn')?.addEventListener('click', () => $('#mcp-edit-modal').classList.add('hidden'));
    $('#mcp-edit-modal .close-btn')?.addEventListener('click', () => $('#mcp-edit-modal').classList.add('hidden'));
    
    // MCP 类型切换
    $('#mcp-type')?.addEventListener('change', (e) => {
        const isRemote = e.target.value === 'remote';
        $('#mcp-url-group').classList.toggle('hidden', !isRemote);
        $('#mcp-command-group').classList.toggle('hidden', isRemote);
    });
}

async function loadSandboxData() {
    await Promise.all([loadAgentList(), loadSkillList(), loadMcpList()]);
}

// ==================== Agent 管理 ====================
async function loadAgentList() {
    try {
        sandboxAgents = await Api.getAgents();
        renderAgentList();
    } catch (err) {
        console.error('Load agents error:', err);
    }
}

function renderAgentList() {
    const container = $('#agent-list');
    if (!container) return;
    
    if (!sandboxAgents.length) {
        container.innerHTML = '<div class="empty-state">暂无 Agent，点击上方按钮添加</div>';
        return;
    }
    
    container.innerHTML = sandboxAgents.map(agent => `
        <div class="config-card ${agent.enabled ? '' : 'disabled'}">
            <div class="config-info">
                <div class="config-name">
                    ${agent.name}
                    <span class="badge badge-mode">${agent.mode}</span>
                    ${!agent.enabled ? '<span class="badge badge-disabled">已禁用</span>' : ''}
                </div>
                <div class="config-desc">${agent.description}</div>
            </div>
            <div class="config-actions">
                <button onclick="openAgentModal(${agent.id})">编辑</button>
                <button class="btn-delete" onclick="deleteAgent(${agent.id})">删除</button>
            </div>
        </div>
    `).join('');
}

function openAgentModal(agentId = null) {
    const modal = $('#agent-edit-modal');
    const title = $('#agent-edit-title');
    
    // 重置表单
    $('#agent-form').reset();
    $('#agent-id').value = '';
    
    if (agentId) {
        const agent = sandboxAgents.find(a => a.id === agentId);
        if (!agent) return;
        
        title.textContent = '编辑 Agent';
        $('#agent-id').value = agent.id;
        $('#agent-name').value = agent.name;
        $('#agent-name').readOnly = true;
        $('#agent-description').value = agent.description;
        $('#agent-mode').value = agent.mode;
        $('#agent-enabled').checked = agent.enabled;
        $('#agent-temperature').value = agent.temperature || '';
        $('#agent-max-steps').value = agent.max_steps || '';
        $('#agent-hidden').checked = agent.hidden;
        $('#agent-content').value = agent.content;
        
        // 工具权限
        $$('#agent-tools input[name="tool"]').forEach(cb => {
            cb.checked = agent.tools[cb.value] !== false;
        });
        
        // 操作权限
        $('#agent-perm-edit').value = agent.permission?.edit || 'allow';
        $('#agent-perm-bash').value = agent.permission?.bash || 'allow';
        $('#agent-perm-webfetch').value = agent.permission?.webfetch || 'allow';
    } else {
        title.textContent = '添加 Agent';
        $('#agent-name').readOnly = false;
    }
    
    // 初始化 Markdown 预览
    updateAgentContentPreview();
    modal.classList.remove('hidden');
}

function updateAgentContentPreview() {
    const content = $('#agent-content').value;
    const preview = $('#agent-content-preview');
    if (preview) {
        preview.innerHTML = renderMarkdownSimple(content);
    }
}

function renderMarkdownSimple(md) {
    if (!md) return '<p>预览区域</p>';
    
    let html = escapeHtml(md)
        // 代码块
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
        // 行内代码
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        // 标题
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/^# (.+)$/gm, '<h1>$1</h1>')
        // 粗体和斜体
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        // 链接
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>')
        // 无序列表
        .replace(/^- (.+)$/gm, '<li>$1</li>')
        // 有序列表
        .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
        // 引用
        .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
        // 段落
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
    
    // 包装列表项
    html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');
    html = html.replace(/<\/ul>\s*<ul>/g, '');
    
    return sanitizeMarkdownHtml('<p>' + html + '</p>');
}

function initAgentContentEditor() {
    const textarea = $('#agent-content');
    const preview = $('#agent-content-preview');
    
    if (!textarea || !preview) return;
    
    // 输入时更新预览
    textarea.addEventListener('input', updateAgentContentPreview);
    
    // 同步滚动
    let syncingScroll = false;
    
    textarea.addEventListener('scroll', () => {
        if (syncingScroll) return;
        syncingScroll = true;
        const scrollRatio = textarea.scrollTop / (textarea.scrollHeight - textarea.clientHeight || 1);
        preview.scrollTop = scrollRatio * (preview.scrollHeight - preview.clientHeight);
        setTimeout(() => syncingScroll = false, 50);
    });
    
    preview.addEventListener('scroll', () => {
        if (syncingScroll) return;
        syncingScroll = true;
        const scrollRatio = preview.scrollTop / (preview.scrollHeight - preview.clientHeight || 1);
        textarea.scrollTop = scrollRatio * (textarea.scrollHeight - textarea.clientHeight);
        setTimeout(() => syncingScroll = false, 50);
    });
}

async function saveAgent() {
    const id = $('#agent-id').value;
    const name = $('#agent-name').value.trim();
    const description = $('#agent-description').value.trim();
    
    if (!name || !description) {
        alert('请填写名称和描述');
        return;
    }
    
    // 收集工具权限
    const tools = {};
    $$('#agent-tools input[name="tool"]').forEach(cb => {
        tools[cb.value] = cb.checked;
    });
    
    // 收集操作权限
    const permission = {
        edit: $('#agent-perm-edit').value,
        bash: $('#agent-perm-bash').value,
        webfetch: $('#agent-perm-webfetch').value,
    };
    
    const data = {
        name,
        description,
        mode: $('#agent-mode').value,
        enabled: $('#agent-enabled').checked,
        tools,
        permission,
        temperature: $('#agent-temperature').value ? parseFloat($('#agent-temperature').value) : null,
        max_steps: $('#agent-max-steps').value ? parseInt($('#agent-max-steps').value) : null,
        hidden: $('#agent-hidden').checked,
        content: $('#agent-content').value,
    };
    
    try {
        if (id) {
            await Api.updateAgent(id, data);
        } else {
            await Api.createAgent(data);
        }
        $('#agent-edit-modal').classList.add('hidden');
        await loadAgentList();
    } catch (err) {
        alert('保存失败: ' + (err.message || err));
    }
}

async function deleteAgent(agentId) {
    if (!confirm('确定要删除这个 Agent 吗？')) return;
    
    try {
        await Api.deleteAgent(agentId);
        await loadAgentList();
    } catch (err) {
        alert('删除失败: ' + (err.message || err));
    }
}

// ==================== Skill 管理 ====================
async function loadSkillList() {
    try {
        sandboxSkills = await Api.getSkills();
        renderSkillList();
    } catch (err) {
        console.error('Load skills error:', err);
    }
}

function renderSkillList() {
    const container = $('#skill-list');
    if (!container) return;
    
    if (!sandboxSkills.length) {
        container.innerHTML = '<div class="empty-state">暂无 Skill，点击上方按钮上传</div>';
        return;
    }
    
    container.innerHTML = sandboxSkills.map(skill => `
        <div class="config-card ${skill.enabled ? '' : 'disabled'}">
            <div class="config-info" style="cursor:pointer" onclick="openSkillDetail(${skill.id})">
                <div class="config-name">
                    ${skill.name}
                    ${!skill.enabled ? '<span class="badge badge-disabled">已禁用</span>' : ''}
                </div>
                <div class="config-desc">${skill.description}</div>
            </div>
            <div class="config-actions">
                <button onclick="event.stopPropagation();toggleSkill(${skill.id})">${skill.enabled ? '禁用' : '启用'}</button>
                <button onclick="event.stopPropagation();openSkillPermModal(${skill.id})">权限</button>
                <button class="btn-delete" onclick="event.stopPropagation();deleteSkill(${skill.id})">删除</button>
            </div>
        </div>
    `).join('');
}

function openSkillUploadModal() {
    const modal = $('#skill-upload-modal');
    const status = $('#skill-upload-status');
    status.classList.add('hidden');
    status.className = 'upload-status hidden';
    modal.classList.remove('hidden');
}

function initSkillUpload() {
    const zone = $('#skill-upload-zone');
    const input = $('#skill-file-input');
    if (!zone || !input) return;
    
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleSkillUpload(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => {
        if (input.files.length) handleSkillUpload(input.files[0]);
    });
}

async function handleSkillUpload(file) {
    const status = $('#skill-upload-status');
    status.classList.remove('hidden', 'success', 'error');
    status.classList.add('loading');
    status.textContent = '上传中...';
    
    try {
        await Api.uploadSkill(file);
        status.classList.remove('loading');
        status.classList.add('success');
        status.textContent = '上传成功！';
        await loadSkillList();
        setTimeout(() => $('#skill-upload-modal').classList.add('hidden'), 1000);
    } catch (err) {
        status.classList.remove('loading');
        status.classList.add('error');
        status.textContent = '上传失败: ' + (err.message || err);
    }
}

async function toggleSkill(skillId) {
    try {
        await Api.toggleSkill(skillId);
        await loadSkillList();
    } catch (err) {
        alert('操作失败: ' + (err.message || err));
    }
}

function openSkillPermModal(skillId) {
    const skill = sandboxSkills.find(s => s.id === skillId);
    if (!skill) return;
    
    $('#skill-perm-id').value = skill.id;
    $('#skill-perm-name').textContent = skill.name;
    $('#skill-perm-desc').textContent = skill.description;
    renderSkillAgentPermissions(skill.agent_permissions || []);
    $('#skill-perm-modal').classList.remove('hidden');
}

function renderSkillAgentPermissions(currentPerms) {
    const container = $('#skill-agent-permissions');
    if (!container) return;
    
    if (!sandboxAgents.length) {
        container.innerHTML = '<div class="empty-hint">暂无 Agent，请先添加 Agent</div>';
        return;
    }
    
    container.innerHTML = sandboxAgents.map(agent => {
        const perm = currentPerms.find(p => p.agent_id === agent.id);
        const value = perm ? perm.permission : 'allow';
        return `
            <div class="agent-permission-item">
                <span class="agent-name">${agent.name}</span>
                <select data-agent-id="${agent.id}">
                    <option value="allow" ${value === 'allow' ? 'selected' : ''}>allow (允许)</option>
                    <option value="ask" ${value === 'ask' ? 'selected' : ''}>ask (询问)</option>
                    <option value="deny" ${value === 'deny' ? 'selected' : ''}>deny (禁止)</option>
                </select>
            </div>
        `;
    }).join('');
}

async function saveSkillPermissions() {
    const skillId = $('#skill-perm-id').value;
    const permissions = [];
    $$('#skill-agent-permissions select').forEach(sel => {
        permissions.push({
            agent_id: parseInt(sel.dataset.agentId),
            permission: sel.value
        });
    });
    
    try {
        await Api.updateSkillPermissions(skillId, permissions);
        $('#skill-perm-modal').classList.add('hidden');
        await loadSkillList();
    } catch (err) {
        alert('保存失败: ' + (err.message || err));
    }
}

async function deleteSkill(skillId) {
    if (!confirm('确定要删除此 Skill 吗？')) return;

    try {
        await Api.deleteSkill(skillId);
        await loadSkillList();
    } catch (err) {
        alert('删除失败: ' + (err.message || err));
    }
}

// Skill 详情相关状态
let skillDetailState = {
    skillId: null,
    openTabs: [],
    activeTab: null,
    fileCache: {}
};

async function openSkillDetail(skillId) {
    const skill = sandboxSkills.find(s => s.id === skillId);
    if (!skill) return;

    skillDetailState = { skillId, openTabs: [], activeTab: null, fileCache: {} };

    $('#skill-detail-title').textContent = `Skill: ${skill.name}`;
    $('#skill-file-tabs').innerHTML = '';
    $('#skill-file-viewer').innerHTML = '<div class="skill-file-placeholder">选择文件查看内容</div>';

    try {
        const fileTree = await Api.getSkillFiles(skillId);
        renderSkillFileTree(fileTree);
    } catch (err) {
        $('#skill-file-tree').innerHTML = '<div style="color:#999;padding:1rem">加载失败</div>';
    }

    $('#skill-detail-modal').classList.remove('hidden');
}

function renderSkillFileTree(tree) {
    const container = $('#skill-file-tree');
    container.innerHTML = renderTreeNode(tree.children || [], '');
}

function renderTreeNode(items, parentPath) {
    return items.map(item => {
        const icon = item.type === 'directory' ? '📁' : getFileIcon(item.name);
        const isDir = item.type === 'directory';

        if (isDir) {
            return `
                <div class="tree-item">
                    <div class="tree-item-header" onclick="toggleTreeFolder(this)">
                        <span class="tree-item-icon">${icon}</span>
                        <span class="tree-item-name">${item.name}</span>
                    </div>
                    <div class="tree-children">${renderTreeNode(item.children || [], item.path)}</div>
                </div>
            `;
        } else {
            return `
                <div class="tree-item">
                    <div class="tree-item-header" onclick="openSkillFile('${item.path}', '${item.name}')">
                        <span class="tree-item-icon">${icon}</span>
                        <span class="tree-item-name">${item.name}</span>
                    </div>
                </div>
            `;
        }
    }).join('');
}

function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'md': '📝', 'txt': '📄', 'py': '🐍', 'js': '📜', 'ts': '📜',
        'json': '📋', 'yaml': '📋', 'yml': '📋', 'html': '🌐', 'css': '🎨',
        'sh': '⚙️', 'sql': '🗃️', 'xml': '📰', 'csv': '📊'
    };
    return icons[ext] || '📄';
}

function toggleTreeFolder(header) {
    const children = header.nextElementSibling;
    if (children) {
        children.classList.toggle('collapsed');
        header.classList.toggle('collapsed');
    }
}

async function openSkillFile(filePath, fileName) {
    // 检查是否已打开
    let tab = skillDetailState.openTabs.find(t => t.path === filePath);

    if (!tab) {
        // 加载文件内容
        try {
            const fileData = await Api.getSkillFileContent(skillDetailState.skillId, filePath);
            tab = { path: filePath, name: fileName, data: fileData };
            skillDetailState.openTabs.push(tab);
            skillDetailState.fileCache[filePath] = fileData;
        } catch (err) {
            alert('加载文件失败');
            return;
        }
    }

    skillDetailState.activeTab = filePath;
    renderSkillFileTabs();
    renderSkillFileContent(tab);

    // 高亮树节点
    $$('#skill-file-tree .tree-item-header').forEach(h => h.classList.remove('active'));
    const activeHeader = [...$$('#skill-file-tree .tree-item-header')].find(h => 
        h.onclick?.toString().includes(`'${filePath}'`)
    );
    if (activeHeader) activeHeader.classList.add('active');
}

function renderSkillFileTabs() {
    const container = $('#skill-file-tabs');
    container.innerHTML = skillDetailState.openTabs.map(tab => `
        <div class="skill-file-tab ${tab.path === skillDetailState.activeTab ? 'active' : ''}" 
             onclick="switchSkillTab('${tab.path}')">
            <span>${tab.name}</span>
            <span class="close-tab" onclick="event.stopPropagation();closeSkillTab('${tab.path}')">&times;</span>
        </div>
    `).join('');
}

function switchSkillTab(filePath) {
    const tab = skillDetailState.openTabs.find(t => t.path === filePath);
    if (!tab) return;

    skillDetailState.activeTab = filePath;
    renderSkillFileTabs();
    renderSkillFileContent(tab);
}

function closeSkillTab(filePath) {
    const idx = skillDetailState.openTabs.findIndex(t => t.path === filePath);
    if (idx === -1) return;

    skillDetailState.openTabs.splice(idx, 1);

    if (skillDetailState.activeTab === filePath) {
        if (skillDetailState.openTabs.length > 0) {
            const newActive = skillDetailState.openTabs[Math.max(0, idx - 1)];
            skillDetailState.activeTab = newActive.path;
            renderSkillFileTabs();
            renderSkillFileContent(newActive);
        } else {
            skillDetailState.activeTab = null;
            renderSkillFileTabs();
            $('#skill-file-viewer').innerHTML = '<div class="skill-file-placeholder">选择文件查看内容</div>';
        }
    } else {
        renderSkillFileTabs();
    }
}

function renderSkillFileContent(tab) {
    const viewer = $('#skill-file-viewer');
    const { data, name } = tab;

    if (data.type === 'binary') {
        viewer.innerHTML = `
            <div class="skill-binary-viewer">
                <div class="file-icon">📦</div>
                <div>二进制文件 (${formatFileSize(data.size)})</div>
            </div>
        `;
        return;
    }

    const ext = name.split('.').pop().toLowerCase();

    if (ext === 'md') {
        // Markdown 双列显示
        viewer.innerHTML = `
            <div class="skill-md-viewer">
                <div class="skill-md-source" id="skill-md-source">${escapeHtml(data.content)}</div>
                <div class="skill-md-preview md-preview" id="skill-md-preview">${renderMarkdownSimple(data.content)}</div>
            </div>
        `;
        initSkillMdSync();
    } else {
        // 代码显示
        viewer.innerHTML = `<div class="skill-code-viewer">${escapeHtml(data.content)}</div>`;
    }
}

function initSkillMdSync() {
    const source = $('#skill-md-source');
    const preview = $('#skill-md-preview');
    if (!source || !preview) return;

    let syncing = false;
    source.addEventListener('scroll', () => {
        if (syncing) return;
        syncing = true;
        const ratio = source.scrollTop / (source.scrollHeight - source.clientHeight || 1);
        preview.scrollTop = ratio * (preview.scrollHeight - preview.clientHeight);
        setTimeout(() => syncing = false, 50);
    });
    preview.addEventListener('scroll', () => {
        if (syncing) return;
        syncing = true;
        const ratio = preview.scrollTop / (preview.scrollHeight - preview.clientHeight || 1);
        source.scrollTop = ratio * (source.scrollHeight - source.clientHeight);
        setTimeout(() => syncing = false, 50);
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

// ==================== MCP 管理 ====================
async function loadMcpList() {
    try {
        sandboxMcps = await Api.getMcps();
        renderMcpList();
    } catch (err) {
        console.error('Load mcps error:', err);
    }
}

function renderMcpList() {
    const container = $('#mcp-list');
    if (!container) return;
    
    if (!sandboxMcps.length) {
        container.innerHTML = '<div class="empty-state">暂无 MCP，点击上方按钮添加</div>';
        return;
    }
    
    container.innerHTML = sandboxMcps.map(mcp => `
        <div class="config-card ${mcp.enabled ? '' : 'disabled'}">
            <div class="config-info">
                <div class="config-name">
                    ${mcp.name}
                    <span class="badge badge-type">${mcp.mcp_type}</span>
                    ${!mcp.enabled ? '<span class="badge badge-disabled">已禁用</span>' : ''}
                </div>
                <div class="config-desc">${mcp.mcp_type === 'remote' ? mcp.url : (mcp.command?.join(' ') || '')}</div>
            </div>
            <div class="config-actions">
                <button onclick="openMcpModal(${mcp.id})">编辑</button>
                <button class="btn-delete" onclick="deleteMcp(${mcp.id})">删除</button>
            </div>
        </div>
    `).join('');
}

function openMcpModal(mcpId = null) {
    const modal = $('#mcp-edit-modal');
    const title = $('#mcp-edit-title');
    
    // 重置表单
    $('#mcp-form').reset();
    $('#mcp-id').value = '';
    $('#mcp-url-group').classList.remove('hidden');
    $('#mcp-command-group').classList.add('hidden');
    
    if (mcpId) {
        const mcp = sandboxMcps.find(m => m.id === mcpId);
        if (!mcp) return;
        
        title.textContent = '编辑 MCP';
        $('#mcp-id').value = mcp.id;
        $('#mcp-name').value = mcp.name;
        $('#mcp-name').readOnly = true;
        $('#mcp-type').value = mcp.mcp_type;
        $('#mcp-enabled').checked = mcp.enabled;
        $('#mcp-url').value = mcp.url || '';
        $('#mcp-command').value = mcp.command ? JSON.stringify(mcp.command) : '';
        $('#mcp-headers').value = mcp.headers ? JSON.stringify(mcp.headers, null, 2) : '';
        $('#mcp-environment').value = mcp.environment ? JSON.stringify(mcp.environment, null, 2) : '';
        
        // 切换显示
        const isRemote = mcp.mcp_type === 'remote';
        $('#mcp-url-group').classList.toggle('hidden', !isRemote);
        $('#mcp-command-group').classList.toggle('hidden', isRemote);
    } else {
        title.textContent = '添加 MCP';
        $('#mcp-name').readOnly = false;
    }
    
    modal.classList.remove('hidden');
}

async function saveMcp() {
    const id = $('#mcp-id').value;
    const name = $('#mcp-name').value.trim();
    const mcpType = $('#mcp-type').value;
    
    if (!name) {
        alert('请填写名称');
        return;
    }
    
    let command = [];
    let headers = {};
    let environment = {};
    
    try {
        if ($('#mcp-command').value.trim()) {
            command = JSON.parse($('#mcp-command').value);
        }
        if ($('#mcp-headers').value.trim()) {
            headers = JSON.parse($('#mcp-headers').value);
        }
        if ($('#mcp-environment').value.trim()) {
            environment = JSON.parse($('#mcp-environment').value);
        }
    } catch (e) {
        alert('JSON 格式错误: ' + e.message);
        return;
    }
    
    const data = {
        name,
        mcp_type: mcpType,
        enabled: $('#mcp-enabled').checked,
        url: mcpType === 'remote' ? $('#mcp-url').value.trim() : null,
        command: mcpType === 'local' ? command : [],
        headers,
        environment,
    };
    
    try {
        if (id) {
            await Api.updateMcp(id, data);
        } else {
            await Api.createMcp(data);
        }
        $('#mcp-edit-modal').classList.add('hidden');
        await loadMcpList();
    } catch (err) {
        alert('保存失败: ' + (err.message || err));
    }
}

async function deleteMcp(mcpId) {
    if (!confirm('确定要删除这个 MCP 吗？')) return;
    
    try {
        await Api.deleteMcp(mcpId);
        await loadMcpList();
    } catch (err) {
        alert('删除失败: ' + (err.message || err));
    }
}
