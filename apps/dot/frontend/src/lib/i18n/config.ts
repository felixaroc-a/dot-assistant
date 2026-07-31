import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import es from './locales/es.json'
import en from './locales/en.json'
import pt from './locales/pt.json'

const savedLang = typeof window !== 'undefined' ? localStorage.getItem('dot-lang') : null

i18n.use(initReactI18next).init({
  resources: { es: { translation: es }, en: { translation: en }, pt: { translation: pt } },
  lng: savedLang || 'es',
  fallbackLng: 'es',
  interpolation: { escapeValue: false },
})

export default i18n
