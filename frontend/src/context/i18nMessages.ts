export type Locale = 'el' | 'en';

type Messages = {
  languageToggleLabel: string;
  languageNameEl: string;
  languageNameEn: string;
  tabWorkspace: string;
  tabHistory: string;
  tabAccount: string;
  subtitleDesk: string;
  signOut: string;
};

export const defaultLocale: Locale = 'el';

export const messages: Record<Locale, Messages> = {
  el: {
    languageToggleLabel: 'Αλλαγή γλώσσας',
    languageNameEl: 'Ελληνικά',
    languageNameEn: 'Αγγλικά',
    tabWorkspace: 'Χώρος εργασίας',
    tabHistory: 'Ιστορικό',
    tabAccount: 'Λογαριασμός',
    subtitleDesk: 'Κέντρο υποτίτλων',
    signOut: 'Αποσύνδεση',
  },
  en: {
    languageToggleLabel: 'Change language',
    languageNameEl: 'Greek',
    languageNameEn: 'English',
    tabWorkspace: 'Workspace',
    tabHistory: 'History',
    tabAccount: 'Account',
    subtitleDesk: 'Subtitle desk',
    signOut: 'Sign Out',
  },
};

export const locales: Locale[] = Object.keys(messages) as Locale[];
