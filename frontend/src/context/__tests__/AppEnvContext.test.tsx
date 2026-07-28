import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
    AppEnvProvider,
    useAppEnv,
} from '@/context/AppEnvContext';

function EnvironmentConsumer() {
    const { appEnv } = useAppEnv();
    return <p>{appEnv}</p>;
}

describe('AppEnvContext', () => {
    it('provides the configured application environment', () => {
        render(
            <AppEnvProvider appEnv="production">
                <EnvironmentConsumer />
            </AppEnvProvider>,
        );

        expect(screen.getByText('production')).toBeInTheDocument();
    });
});
