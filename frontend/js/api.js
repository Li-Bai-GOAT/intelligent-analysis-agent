const API_BASE = '/api';

class Api {
    static token = localStorage.getItem('token');
    static user = JSON.parse(localStorage.getItem('user') || 'null');

    static setAuth(token, user) {
        this.token = token;
        this.user = user;
        localStorage.setItem('token', token);
        localStorage.setItem('user', JSON.stringify(user));
    }

    static clearAuth() {
        this.token = null;
        this.user = null;
        localStorage.removeItem('token');
        localStorage.removeItem('user');
    }

    static headers(extra = {}) {
        const h = { 'Content-Type': 'application/json', ...extra };
        if (this.token) h['Authorization'] = `Bearer ${this.token}`;
        return h;
    }

    static async request(method, path, body = null) {
        const opts = { method, headers: this.headers() };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`${API_BASE}${path}`, opts);
        if (res.status === 401) {
            this.clearAuth();
            location.reload();
            throw new Error('未授权');
        }
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || '请求失败');
        return data;
    }

    // Auth
    static register(username, password) {
        return this.request('POST', '/auth/register', { username, password });
    }

    static async login(username, password) {
        const data = await this.request('POST', '/auth/login', { username, password });
        this.setAuth(data.access_token, data.user);
        return data;
    }

    // Sessions
    static listSessions() {
        return this.request('GET', '/sessions');
    }

    static getSession(sessionId) {
        return this.request('GET', `/sessions/${sessionId}`);
    }

    static deleteSession(sessionId) {
        return this.request('DELETE', `/sessions/${sessionId}`);
    }

    static createSession() {
        return this.request('POST', '/conversation/sessions');
    }

    // Async Chat
    static async submitTask(sessionId, message, fileIds = []) {
        return this.request('POST', '/conversation/async', {
            session_id: sessionId,
            message,
            file_ids: fileIds
        });
    }

    static async getSessionTask(sessionId) {
        return this.request('GET', `/conversation/session/${sessionId}/task`);
    }

    static streamTask(taskId, onMessage, onDone) {
        // EventSource cannot attach Authorization headers. Fetch streaming keeps
        // task output behind the same Bearer token as every other API request.
        const controller = new AbortController();
        let finished = false;
        let lastEventId = '0';
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 3;

        const finish = (data) => {
            if (finished) return;
            finished = true;
            onDone(data);
        };

        const consume = async () => {
            try {
                const headers = this.headers({ Accept: 'text/event-stream' });
                if (lastEventId !== '0') headers['Last-Event-ID'] = lastEventId;
                const response = await fetch(`${API_BASE}/conversation/stream/${taskId}`, {
                    method: 'GET',
                    headers,
                    signal: controller.signal,
                });
                if (!response.ok || !response.body) {
                    let detail = '任务流连接失败';
                    try {
                        const body = await response.json();
                        detail = body.detail || detail;
                    } catch (err) {}
                    throw new Error(detail);
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                const handleEvent = (rawEvent) => {
                    const eventId = rawEvent
                        .split(/\r?\n/)
                        .find((line) => line.startsWith('id:'));
                    if (eventId) lastEventId = eventId.slice(3).trim();
                    const dataText = rawEvent
                        .split(/\r?\n/)
                        .filter((line) => line.startsWith('data:'))
                        .map((line) => line.slice(5).trimStart())
                        .join('\n');
                    if (!dataText || dataText === '[DONE]') return;

                    try {
                        const data = JSON.parse(dataText);
                        if (data.type === 'end' || data.type === 'error') {
                            finish(data);
                        } else {
                            onMessage(data);
                        }
                    } catch (err) {
                        console.error('SSE parse error:', err);
                    }
                };

                while (!finished) {
                    const { value, done } = await reader.read();
                    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
                    const events = buffer.split(/\r?\n\r?\n/);
                    buffer = events.pop() || '';
                    events.forEach(handleEvent);
                    if (done) break;
                }

                if (!finished && !controller.signal.aborted) {
                    if (reconnectAttempts < maxReconnectAttempts) {
                        reconnectAttempts += 1;
                        await new Promise((resolve) => setTimeout(resolve, reconnectAttempts * 800));
                        if (!controller.signal.aborted) await consume();
                    } else {
                        finish({ type: 'error', content: '任务流意外结束' });
                    }
                }
            } catch (err) {
                if (!controller.signal.aborted) {
                    if (reconnectAttempts < maxReconnectAttempts) {
                        reconnectAttempts += 1;
                        await new Promise((resolve) => setTimeout(resolve, reconnectAttempts * 800));
                        if (!controller.signal.aborted) await consume();
                    } else {
                        finish({ type: 'error', content: err.message || '任务流连接失败' });
                    }
                }
            }
        };

        void consume();
        return { close: () => controller.abort() };
    }

    // Files
    static async uploadFiles(sessionId, files) {
        const formData = new FormData();
        for (const f of files) formData.append('files', f);
        const res = await fetch(`${API_BASE}/files/upload?session_id=${sessionId}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${this.token}` },
            body: formData
        });
        if (!res.ok) throw new Error('上传失败');
        return res.json();
    }

    static listUploadedFiles(sessionId) {
        return this.request('GET', `/files/uploads/${sessionId}/list`);
    }

    static listSandboxWorkspace(sessionId, path = '') {
        const params = path ? `?path=${encodeURIComponent(path)}` : '';
        return this.request('GET', `/files/sandbox/${sessionId}/workspace${params}`);
    }

    static getSandboxFileContent(sessionId, path) {
        return this.request('GET', `/files/sandbox/${sessionId}/workspace/content?path=${encodeURIComponent(path)}`);
    }

    static saveSandboxFileContent(sessionId, path, content) {
        return this.request('PUT', `/files/sandbox/${sessionId}/workspace/content?path=${encodeURIComponent(path)}`, { content });
    }

    static getSandboxFileDownloadUrl(sessionId, path) {
        return `${API_BASE}/files/sandbox/${sessionId}/workspace/download?path=${encodeURIComponent(path)}`;
    }

    static getSandboxZipDownloadUrl(sessionId) {
        return `${API_BASE}/files/sandbox/${sessionId}/workspace/zip`;
    }

    // Knowledge
    static listKnowledge(category = null, limit = 100, offset = 0) {
        let url = `/knowledge?limit=${limit}&offset=${offset}`;
        if (category) url += `&category=${encodeURIComponent(category)}`;
        return this.request('GET', url);
    }

    static createKnowledge(data) {
        return this.request('POST', '/knowledge', data);
    }

    static updateKnowledge(id, data) {
        return this.request('PUT', `/knowledge/${id}`, data);
    }

    static deleteKnowledge(id) {
        return this.request('DELETE', `/knowledge/${id}`);
    }

    // System Prompt
    static getSystemPrompt() {
        return this.request('GET', '/system-prompt');
    }

    static updateSystemPrompt(content) {
        return this.request('PUT', '/system-prompt', { content });
    }

    // ==================== Sandbox Management ====================
    // Agents
    static getAgents() {
        return this.request('GET', '/sandbox/agents');
    }

    static getAgent(id) {
        return this.request('GET', `/sandbox/agents/${id}`);
    }

    static createAgent(data) {
        return this.request('POST', '/sandbox/agents', data);
    }

    static updateAgent(id, data) {
        return this.request('PUT', `/sandbox/agents/${id}`, data);
    }

    static deleteAgent(id) {
        return this.request('DELETE', `/sandbox/agents/${id}`);
    }

    // Skills
    static getSkills() {
        return this.request('GET', '/sandbox/skills');
    }

    static getSkill(id) {
        return this.request('GET', `/sandbox/skills/${id}`);
    }

    static async uploadSkill(file) {
        const formData = new FormData();
        formData.append('file', file);
        const headers = {};
        if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
        const response = await fetch(`${API_BASE}/sandbox/skills/upload`, {
            method: 'POST',
            headers,
            body: formData
        });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || '上传失败');
        }
        return response.json();
    }

    static toggleSkill(id) {
        return this.request('PATCH', `/sandbox/skills/${id}/toggle`);
    }

    static deleteSkill(id) {
        return this.request('DELETE', `/sandbox/skills/${id}`);
    }

    static updateSkillPermissions(skillId, permissions) {
        return this.request('PUT', `/sandbox/skills/${skillId}/permissions`, permissions);
    }

    static getSkillFiles(skillId) {
        return this.request('GET', `/sandbox/skills/${skillId}/files`);
    }

    static getSkillFileContent(skillId, filePath) {
        return this.request('GET', `/sandbox/skills/${skillId}/files/${encodeURIComponent(filePath)}`);
    }

    // MCPs
    static getMcps() {
        return this.request('GET', '/sandbox/mcps');
    }

    static getMcp(id) {
        return this.request('GET', `/sandbox/mcps/${id}`);
    }

    static createMcp(data) {
        return this.request('POST', '/sandbox/mcps', data);
    }

    static updateMcp(id, data) {
        return this.request('PUT', `/sandbox/mcps/${id}`, data);
    }

    static deleteMcp(id) {
        return this.request('DELETE', `/sandbox/mcps/${id}`);
    }

    // Injection
    static injectToSandbox(containerId) {
        return this.request('POST', '/sandbox/inject', { container_id: containerId });
    }
}
