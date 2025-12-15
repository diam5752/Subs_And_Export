'use client';

import React, { createContext, useContext } from 'react';
import type { AppEnv } from '@/lib/appEnv';

type AppEnvContextValue = {
  appEnv: AppEnv;
};

const AppEnvContext = createContext<AppEnvContextValue>({ appEnv: 'dev' });

export function AppEnvProvider({
  appEnv,
  children,
}: {
  appEnv: AppEnv;
  children: React.ReactNode;
}) {
  return <AppEnvContext.Provider value={{ appEnv }}>{children}</AppEnvContext.Provider>;
}

export function useAppEnv(): AppEnvContextValue {
  return useContext(AppEnvContext);
}
