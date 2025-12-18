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
    transcription_url?: string;
    source_gcs_object?: string;
    social?: string | null;
    original_filename?: string | null;
    video_crf?: number;
    model_size?: string;
    transcribe_provider?: string;
    output_size?: number;
    resolution?: string;
    variants?: Record<string, string>;
}

export interface JobResponse {
    id: string;
    status: string;
    progress: number;
    message: string | null;
    created_at: number;
    updated_at: number;
    result_data: JobResultData | null;
    balance?: number | null;
}

export interface GcsUploadUrlResponse {
    upload_id: string;
    object_name: string;
    upload_url: string;
    expires_at: number;
    required_headers: Record<string, string>;
}

export interface HistoryEvent {
    ts: string;
    user_id: string;
    email: string;
    kind: string;
    summary: string;
    data: Record<string, unknown>;
}

export interface UserResponse {
    id: string;
    email: string;
    name: string;
    provider: string;
}

export interface PointsBalanceResponse {
    balance: number;
}

export interface ExportDataResponse {
    profile: UserResponse;
    jobs: JobResponse[];
    history: HistoryEvent[];
}



export interface PaginatedJobsResponse {
    items: JobResponse[];
    total: number;
    page: number;
    page_size: number;
    total_pages: number;
}

export interface TranscriptionWordTiming {
    start: number;
    end: number;
    text: string;
}

export interface TranscriptionCue {
    start: number;
    end: number;
    text: string;
    words?: TranscriptionWordTiming[] | null;
}





class ApiClient {
    private token: string | null = null;

    constructor() {
        /* istanbul ignore next */
        if (typeof window !== 'undefined') {
            this.token = localStorage.getItem('auth_token');
        }
    }

    setToken(token: string) {
        this.token = token;
        /* istanbul ignore next */
        if (typeof window !== 'undefined') {
            localStorage.setItem('auth_token', token);
        }
    }

    clearToken() {
        this.token = null;
        /* istanbul ignore next */
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

    async getPointsBalance(): Promise<PointsBalanceResponse> {
        return this.request<PointsBalanceResponse>('/auth/points');
    }

    async processVideo(file: File, settings: {
        transcribe_model?: string;
        transcribe_provider?: string;
        openai_model?: string;
        video_quality?: string;
        video_resolution?: string;
        use_llm?: boolean;
        context_prompt?: string;
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
    }): Promise<JobResponse> {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('transcribe_model', settings.transcribe_model || 'medium');
        formData.append('transcribe_provider', settings.transcribe_provider || 'local');
        formData.append('openai_model', settings.openai_model || '');
        formData.append('video_quality', settings.video_quality || 'balanced');
        formData.append('video_resolution', settings.video_resolution || '');
        formData.append('use_llm', String(settings.use_llm || false));
        formData.append('context_prompt', settings.context_prompt || '');
        formData.append('subtitle_position', String(settings.subtitle_position ?? 16));
        formData.append('max_subtitle_lines', String(settings.max_subtitle_lines ?? 2));
        if (settings.subtitle_color) {
            formData.append('subtitle_color', settings.subtitle_color);
        }
        if (settings.shadow_strength !== undefined) {
            formData.append('shadow_strength', String(settings.shadow_strength));
        }
        if (settings.highlight_style) {
            formData.append('highlight_style', settings.highlight_style);
        }
        formData.append('subtitle_size', String(settings.subtitle_size ?? 100));
        formData.append('karaoke_enabled', String(settings.karaoke_enabled ?? true));

        return this.request<JobResponse>('/videos/process', {
            method: 'POST',
            body: formData,
        });
    }

    async createGcsUploadUrl(file: File): Promise<GcsUploadUrlResponse> {
        const contentType = file.type || 'application/octet-stream';
        return this.request<GcsUploadUrlResponse>('/videos/gcs/upload-url', {
            method: 'POST',
            body: JSON.stringify({
                filename: file.name,
                content_type: contentType,
                size_bytes: file.size,
            }),
        });
    }

    async uploadToSignedUrl(
        uploadUrl: string,
        file: File,
        contentType: string,
        onProgress?: (percent: number) => void,
    ): Promise<void> {
        await new Promise<void>((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('PUT', uploadUrl);
            xhr.setRequestHeader('Content-Type', contentType);

            xhr.upload.onprogress = (event) => {
                if (!onProgress) return;
                if (!event.lengthComputable || event.total <= 0) return;
                onProgress(Math.round((event.loaded / event.total) * 100));
            };

            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve();
                    return;
                }
                reject(new Error(`Upload failed with status ${xhr.status}`));
            };
            xhr.onerror = () => reject(new Error('Upload failed'));
            xhr.send(file);
        });
    }

    async processVideoFromGcs(uploadId: string, settings: {
        transcribe_model?: string;
        transcribe_provider?: string;
        openai_model?: string;
        video_quality?: string;
        video_resolution?: string;
        use_llm?: boolean;
        context_prompt?: string;
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
    }): Promise<JobResponse> {
        return this.request<JobResponse>('/videos/gcs/process', {
            method: 'POST',
            body: JSON.stringify({
                upload_id: uploadId,
                transcribe_model: settings.transcribe_model || 'medium',
                transcribe_provider: settings.transcribe_provider || 'local',
                openai_model: settings.openai_model || '',
                video_quality: settings.video_quality || 'balanced',
                video_resolution: settings.video_resolution || '',
                use_llm: Boolean(settings.use_llm),
                context_prompt: settings.context_prompt || '',
                subtitle_position: settings.subtitle_position ?? 16,
                max_subtitle_lines: settings.max_subtitle_lines ?? 2,
                subtitle_color: settings.subtitle_color ?? null,
                shadow_strength: settings.shadow_strength ?? 4,
                highlight_style: settings.highlight_style || 'karaoke',
                subtitle_size: settings.subtitle_size ?? 100,
                karaoke_enabled: settings.karaoke_enabled ?? true,
            }),
        });
    }

    async loadDevSampleJob(provider?: string, model_size?: string): Promise<JobResponse> {
        return this.request<JobResponse>('/dev/sample-job', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ provider, model_size }),
        });
    }

    async getJobStatus(jobId: string): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}`);
    }

    async getJobs(): Promise<JobResponse[]> {
        return this.request<JobResponse[]>('/videos/jobs');
    }

    async getJobsPaginated(page: number = 1, pageSize: number = 5): Promise<PaginatedJobsResponse> {
        return this.request<PaginatedJobsResponse>(`/videos/jobs/paginated?page=${page}&page_size=${pageSize}`);
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

    async exportData(): Promise<ExportDataResponse> {
        return this.request<ExportDataResponse>('/auth/export');
    }

    async deleteAccount(): Promise<{ status: string; message: string }> {
        const response = await this.request<{ status: string; message: string }>('/auth/me', {
            method: 'DELETE',
        });
        this.clearToken();
        return response;
    }

    async deleteJob(jobId: string): Promise<{ status: string; job_id: string }> {
        return this.request<{ status: string; job_id: string }>(`/videos/jobs/${jobId}`, {
            method: 'DELETE',
        });
    }

    async deleteJobs(jobIds: string[]): Promise<{ status: string; deleted_count: number }> {
        return this.request<{ status: string; deleted_count: number }>('/videos/jobs/batch', {
            method: 'DELETE',
            body: JSON.stringify({ job_ids: jobIds }),
        });
    }

    async cancelJob(jobId: string): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}/cancel`, {
            method: 'POST',
        });
    }

    async exportVideo(jobId: string, resolution: string, settings?: {
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
    }): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}/export`, {
            method: 'POST',
            body: JSON.stringify({ resolution, ...settings }),
        });
    }

    async reprocessJob(jobId: string, settings: {
        transcribe_model?: string;
        transcribe_provider?: string;
        openai_model?: string;
        video_quality?: string;
        video_resolution?: string;
        use_llm?: boolean;
        context_prompt?: string;
        subtitle_position?: number;
        max_subtitle_lines?: number;
        subtitle_color?: string | null;
        shadow_strength?: number;
        highlight_style?: string;
        subtitle_size?: number;
        karaoke_enabled?: boolean;
    }): Promise<JobResponse> {
        return this.request<JobResponse>(`/videos/jobs/${jobId}/reprocess`, {
            method: 'POST',
            body: JSON.stringify({
                transcribe_model: settings.transcribe_model || 'medium',
                transcribe_provider: settings.transcribe_provider || 'local',
                openai_model: settings.openai_model || '',
                video_quality: settings.video_quality || 'balanced',
                video_resolution: settings.video_resolution || '',
                use_llm: Boolean(settings.use_llm),
                context_prompt: settings.context_prompt || '',
                subtitle_position: settings.subtitle_position ?? 16,
                max_subtitle_lines: settings.max_subtitle_lines ?? 2,
                subtitle_color: settings.subtitle_color ?? null,
                shadow_strength: settings.shadow_strength ?? 4,
                highlight_style: settings.highlight_style || 'karaoke',
                subtitle_size: settings.subtitle_size ?? 100,
                karaoke_enabled: settings.karaoke_enabled ?? true,
            }),
        });
    }

    async updateJobTranscription(jobId: string, cues: TranscriptionCue[]): Promise<{ status: string }> {
        return this.request<{ status: string }>(`/videos/jobs/${jobId}/transcription`, {
            method: 'PUT',
            body: JSON.stringify({ cues }),
        });
    }



    async factCheck(jobId: string): Promise<FactCheckResponse> {
        return this.request<FactCheckResponse>(`/videos/jobs/${jobId}/fact-check`, {
            method: 'POST',
        });
    }
}

export interface FactCheckItem {
    mistake: string;
    correction: string;
    explanation: string;
}

export interface FactCheckResponse {
    items: FactCheckItem[];
    balance?: number | null;
}

export const api = new ApiClient();
