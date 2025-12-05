// Mock fetch globally
global.fetch = jest.fn();

describe('API Client', () => {
    beforeEach(() => {
        (fetch as jest.Mock).mockClear();
        localStorage.clear();
    });

    describe('login', () => {
        it('should call the login endpoint with correct data', async () => {
            const mockResponse = {
                access_token: 'test_token',
                token_type: 'bearer',
                user_id: '123',
                name: 'Test User',
            };

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => mockResponse,
            });

            // Import fresh instance
            const { api } = await import('@/lib/api');
            const result = await api.login('test@example.com', 'password123');

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/token'),
                expect.objectContaining({
                    method: 'POST',
                })
            );
            expect(result.access_token).toBe('test_token');
            expect(localStorage.getItem('auth_token')).toBe('test_token');
        });

        it('should throw error on failed login', async () => {
            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: false,
                json: async () => ({ detail: 'Invalid credentials' }),
            });

            const { api } = await import('@/lib/api');
            await expect(api.login('test@example.com', 'wrong')).rejects.toThrow('Invalid credentials');
        });
    });

    describe('register', () => {
        it('should call the register endpoint with correct data', async () => {
            const mockResponse = {
                id: '123',
                email: 'test@example.com',
                name: 'Test User',
                provider: 'local',
            };

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => mockResponse,
            });

            const { api } = await import('@/lib/api');
            const result = await api.register('test@example.com', 'password123', 'Test User');

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/register'),
                expect.objectContaining({
                    method: 'POST',
                    body: JSON.stringify({
                        email: 'test@example.com',
                        password: 'password123',
                        name: 'Test User',
                    }),
                })
            );
            expect(result.email).toBe('test@example.com');
        });
    });

    describe('getCurrentUser', () => {
        it('should include auth header when token exists', async () => {
            localStorage.setItem('auth_token', 'stored_token');

            (fetch as jest.Mock).mockResolvedValueOnce({
                ok: true,
                json: async () => ({ id: '123', email: 'test@example.com', name: 'Test', provider: 'local' }),
            });

            // Need fresh import to pick up localStorage
            jest.resetModules();
            const { api } = await import('@/lib/api');
            await api.getCurrentUser();

            expect(fetch).toHaveBeenCalledWith(
                expect.stringContaining('/auth/me'),
                expect.objectContaining({
                    headers: expect.objectContaining({
                        Authorization: 'Bearer stored_token',
                    }),
                })
            );
        });
    });
});

describe('Token Management', () => {
    it('should store token in localStorage', async () => {
        const { api } = await import('@/lib/api');
        api.setToken('new_token');
        expect(localStorage.getItem('auth_token')).toBe('new_token');
    });

    it('should clear token from localStorage', async () => {
        localStorage.setItem('auth_token', 'existing_token');
        const { api } = await import('@/lib/api');
        api.clearToken();
        expect(localStorage.getItem('auth_token')).toBeNull();
    });
});
