import type { AppLocale } from '../stores/types';

export const profilePageCopy: Record<
  AppLocale,
  {
    pageTitle: string;
    emailLabel: string;
    alpacaNotSet: string;
    alpacaSaved: string;
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
  }
> = {
  en: {
    pageTitle: 'Profile',
    emailLabel: 'Email',
    alpacaNotSet: 'not set — add them in Settings',
    alpacaSaved: 'saved on server (encrypted)',
    languageLabel: 'Language',
    languageDescription: 'Applies to this screen (Profile) and can be used app-wide. Saved in this browser.',
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
  },
  ko: {
    pageTitle: '프로필',
    emailLabel: '이메일',
    alpacaNotSet: '미설정 — 설정에서 API 키를 추가하세요',
    alpacaSaved: '서버에 저장됨(암호화)',
    languageLabel: '언어',
    languageDescription: '이 화면(프로필)에 반영되며, 앱 전체에 확장될 수 있습니다. 이 브라우저에 저장됩니다.',
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
  },
};
