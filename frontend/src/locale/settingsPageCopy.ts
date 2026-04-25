import type { AppLocale } from '../stores/types';

export const settingsPageCopy: Record<
  AppLocale,
  {
    settingsTitle: string;
    languageLabel: string;
    languageDescription: string;
    english: string;
    korean: string;
    languageEnglishSub: string;
    languageKoreanSub: string;
    appearanceLabel: string;
    appearanceDescription: string;
    dark: string;
    darkSub: string;
    light: string;
    lightSub: string;
    brokerSectionTitle: string;
  }
> = {
  en: {
    settingsTitle: 'Settings',
    languageLabel: 'Language',
    languageDescription:
      'Applies to this page and can be expanded app-wide later. Saved in this browser.',
    english: 'English',
    korean: 'Korean',
    languageEnglishSub: 'Interface in English',
    languageKoreanSub: 'Interface in Korean',
    appearanceLabel: 'Appearance',
    appearanceDescription: 'Theme applies across the app and is saved on this browser.',
    dark: 'Dark',
    darkSub: 'Default trading dashboard',
    light: 'Light',
    lightSub: 'Bright UI for daytime',
    brokerSectionTitle: 'Broker & API keys',
  },
  ko: {
    settingsTitle: '설정',
    languageLabel: '언어',
    languageDescription:
      '이 페이지에 반영되며, 이후 앱 전체로 확장될 수 있습니다. 이 브라우저에 저장됩니다.',
    english: 'English',
    korean: '한국어',
    languageEnglishSub: '영어 인터페이스',
    languageKoreanSub: '한국어 인터페이스',
    appearanceLabel: '화면',
    appearanceDescription: '테마는 앱 전체에 적용되며 이 브라우저에 저장됩니다.',
    dark: '다크',
    darkSub: '기본 대시보드 (어두운 배경)',
    light: '라이트',
    lightSub: '밝은 UI (낮 사용에 적합)',
    brokerSectionTitle: '브로커 · API',
  },
};
