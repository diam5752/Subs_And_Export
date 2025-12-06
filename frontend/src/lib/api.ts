export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface TokenResponse {
    access_token: string;
    token_type: string;
    user_id: string;
    name: string;
}

export interface JobResultData {
    video_path: string;
    artifacts_dir: string;
    public_url?: string;
    artifact_url?: string;
    social?: string | null;
    original_filename?: string | null;
    video_crf?: number;
    model_size?: string;
    transcribe_provider?: string;
}

export interface JobResponse {
    id: string;
    status: string;
    progress: number;
    message: string | null;
    created_at: number;
    updated_at: number;
    result_data: JobResultData | null;
}

export interface HistoryEvent {
    ts: string;
    user_id: string;
    email: string;
    kind: string;
    summary: string;
    data: Record<string, unknown>;
}

interface UserResponse {
    id: string;
    email: string;
    name: string;
    provider: string;
}

class ApiClient {
    private token: string | null = null;

    constructor() {
        if (typeof window !== 'undefined') {
            this.token = localStorage.getItem('auth_token');
        }
    }

    setToken(token: string) {
        this.token = token;
        if (typeof window !== 'undefined') {
            localStorage.setItem('auth_token', token);
        }
    }

    clearToken() {
        this.token = null;
        if (typeof window !== 'undefined') {
            localStorage.removeItem('auth_token');
        }
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<T> {
        const url = `${API_BASE}${endpoint}`;
        const headers: Record<string, string> = {};

        // Copy existing headers
        if (options.headers) {
            const existingHeaders = options.headers as Record<string, string>;
            Object.keys(existingHeaders).forEach(key => {
                headers[key] = existingHeaders[key];
            });
        }

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        // Only set Content-Type to JSON if not already set and body is not FormData/URLSearchParams
        if (!headers['Content-Type'] &&
            !(options.body instanceof FormData) &&
            !(options.body instanceof URLSearchParams)) {
            headers['Content-Type'] = 'application/json';
        }

        const response = await fetch(url, { ...options, headers });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
            // Handle various error formats
            let errorMessage = 'Request failed';
            if (typeof errorData === 'string') {
                errorMessage = errorData;
            } else if (errorData.detail) {
                errorMessage = typeof errorData.detail === 'string'
                    ? errorData.detail
                    : JSON.stringify(errorData.detail);
            } else if (errorData.message) {
                errorMessage = errorData.message;
            }
            throw new Error(errorMessage);
        }

        return response.json();
    }

    async login(email: string, password: string): Promise<TokenResponse> {
        const formData = new URLSearchParams();
        formData.append('username', email);
        formData.append('password', password);

        const response = await this.request<TokenResponse>('/auth/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
        });
        this.setToken(response.access_token);
        return response;
    }

    async register(email: string, password: string, name: string): Promise<UserResponse> {
        return this.request<UserResponse>('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ email, password, name }),
        });
    }

    async getCurrentUser(): Promise<UserResponse> {
        return this.request<UserResponse>('/auth/me');
    }

    async processVideo(file: File, settings: {
        transcribe_model?: string;
        transcribe_provider?: string;
        openai_model?: string;
        video_quality?: string;
        use_llm?: boolean;
        context_prompt?: string;
    }): Promise<JobResponse> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('transcribe_model', settings.transcribe_model || 'medium');
        formData.append('transcribe_provider', settings.transcribe_provider || 'local');
        formData.append('openai_model', settings.openai_model || '');
        formData.append('video_quality', settings.video_quality || 'balanced');
        formData.append('use_llm', String(settings.use_llm || false));
        formData.append('context_prompt', settings.context_prompt || '');

        return this.request<JobResponse>('/videos/process', {
            method: 'POST',
            body: formData,
        });
    }

    async getJobStatus(jobId: string): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}`);
    }

    async getJobs(): Promise<JobResponse[]> {
        return this.request<JobResponse[]>('/videos/jobs');
    }

    async updateProfile(name: string): Promise<UserResponse> {
        return this.request<UserResponse>('/auth/me', {
            method: 'PUT',
            body: JSON.stringify({ name }),
        });
    }

    async updatePassword(password: string, confirm_password: string): Promise<{ status: string }> {
        return this.request('/auth/password', {
            method: 'PUT',
            body: JSON.stringify({ password, confirm_password }),
        });
    }

    async getHistory(limit: number = 50): Promise<HistoryEvent[]> {
        return this.request<HistoryEvent[]>(`/history/?limit=${limit}`);
    }

    async getTikTokAuthUrl(): Promise<{ auth_url: string; state: string }> {
        return this.request('/tiktok/url');
    }

    async tiktokCallback(code: string, state: string): Promise<{ access_token: string }> {
        return this.request('/tiktok/callback', {
            method: 'POST',
            body: JSON.stringify({ code, state }),
        });
    }

    async uploadToTikTok(access_token: string, video_path: string, title: string, description: string): Promise<unknown> {
        return this.request('/tiktok/upload', {
            method: 'POST',
            body: JSON.stringify({ access_token, video_path, title, description }),
        });
    }

    async getGoogleAuthUrl(): Promise<{ auth_url: string; state: string }> {
        return this.request('/auth/google/url');
    }

    async googleCallback(code: string, state: string): Promise<TokenResponse> {
        const response = await this.request<TokenResponse>('/auth/google/callback', {
            method: 'POST',
            body: JSON.stringify({ code, state }),
        });
        this.setToken(response.access_token);
        return response;
    }
}

export const api = new ApiClient();
