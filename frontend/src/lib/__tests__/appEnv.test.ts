import { isDevEnv, normalizeAppEnv } from '@/lib/appEnv';

describe('appEnv', () => {
  describe('normalizeAppEnv', () => {
    it('defaults to dev when unset', () => {
      expect(normalizeAppEnv(undefined)).toBe('dev');
      expect(normalizeAppEnv(null)).toBe('dev');
      expect(normalizeAppEnv('')).toBe('dev');
    });

    it('maps common dev aliases', () => {
      expect(normalizeAppEnv('dev')).toBe('dev');
      expect(normalizeAppEnv('development')).toBe('dev');
      expect(normalizeAppEnv('local')).toBe('dev');
      expect(normalizeAppEnv('localhost')).toBe('dev');
    });

    it('maps common prod aliases', () => {
      expect(normalizeAppEnv('prod')).toBe('production');
      expect(normalizeAppEnv('production')).toBe('production');
    });

    it('treats unknown values as production', () => {
      expect(normalizeAppEnv('staging')).toBe('production');
    });
  });

  describe('isDevEnv', () => {
    it('returns true only for dev', () => {
      expect(isDevEnv('dev')).toBe(true);
      expect(isDevEnv('production')).toBe(false);
    });
  });
});

