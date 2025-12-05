const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface TokenResponse {
    access_token: string;
    token_type: string;
    user_id: string;
    name: string;
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
        video_quality?: string;
        use_llm?: boolean;
        context_prompt?: string;
    }): Promise<{ id: string }> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('transcribe_model', settings.transcribe_model || 'medium');
        formData.append('video_quality', settings.video_quality || 'balanced');
        formData.append('use_llm', String(settings.use_llm || false));
        formData.append('context_prompt', settings.context_prompt || '');

        return this.request('/videos/process', {
            method: 'POST',
            body: formData,
        });
    }

    async getJobStatus(jobId: string): Promise<{
        id: string;
        status: string;
        progress: number;
        message: string | null;
        result_data: Record<string, unknown> | null;
    }> {
        return this.request(`/videos/jobs/${jobId}`);
    }

    async getJobs(): Promise<Array<{ id: string; status: string; progress: number }>> {
        return this.request('/videos/jobs');
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
