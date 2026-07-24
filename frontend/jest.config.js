/* eslint-disable @typescript-eslint/no-require-imports */
const nextJest = require('next/jest');

const createJestConfig = nextJest({
    dir: './',
});

const customJestConfig = {
    setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
    testEnvironment: 'jest-environment-jsdom',
    collectCoverageFrom: [
        'next.config.ts',
        'src/**/*.{ts,tsx}',
        '!src/**/*.d.ts',
        '!src/**/__tests__/**',
        '!src/**/__mocks__/**',
        '!src/app/layout.tsx',
        '!src/app/privacy/page.tsx',
        '!src/app/register/page.tsx',
        '!src/app/terms/page.tsx',
    ],
    coverageThreshold: {
        global: {
            lines: 90,
        },
    },
    moduleNameMapper: {
        '^@/(.*)$': '<rootDir>/src/$1',
    },
    testPathIgnorePatterns: ['<rootDir>/tests/e2e'],
    modulePathIgnorePatterns: [
        '<rootDir>/.next',
        '<rootDir>/test-results',
        '<rootDir>/playwright-report',
    ],
    watchPathIgnorePatterns: [
        '<rootDir>/.next',
        '<rootDir>/test-results',
        '<rootDir>/playwright-report',
    ],
};

module.exports = createJestConfig(customJestConfig);
