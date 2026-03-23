import { create } from 'zustand'

const TEMP_DOUBAO_API_KEY_STORAGE = 'pipeline_temp_doubao_api_key'

interface RuntimeSecretsState {
  temporaryDoubaoApiKey: string
  hydrated: boolean
  apiKeyModalOpen: boolean
  apiKeyModalReason: string
  setTemporaryDoubaoApiKey: (apiKey: string) => void
  clearTemporaryDoubaoApiKey: () => void
  openApiKeyModal: (reason?: string) => void
  closeApiKeyModal: () => void
  hydrate: () => void
}

const readStoredTemporaryDoubaoApiKey = () => {
  if (typeof window === 'undefined') {
    return ''
  }
  return window.sessionStorage.getItem(TEMP_DOUBAO_API_KEY_STORAGE) || ''
}

const persistTemporaryDoubaoApiKey = (apiKey: string) => {
  if (typeof window === 'undefined') {
    return
  }

  const normalized = apiKey.trim()
  if (!normalized) {
    window.sessionStorage.removeItem(TEMP_DOUBAO_API_KEY_STORAGE)
    return
  }

  window.sessionStorage.setItem(TEMP_DOUBAO_API_KEY_STORAGE, normalized)
}

export const useRuntimeSecretsStore = create<RuntimeSecretsState>((set) => ({
  temporaryDoubaoApiKey: '',
  hydrated: false,
  apiKeyModalOpen: false,
  apiKeyModalReason: '',
  setTemporaryDoubaoApiKey: (apiKey) => {
    const normalized = apiKey.trim()
    persistTemporaryDoubaoApiKey(normalized)
    set({ temporaryDoubaoApiKey: normalized, hydrated: true })
  },
  clearTemporaryDoubaoApiKey: () => {
    persistTemporaryDoubaoApiKey('')
    set({ temporaryDoubaoApiKey: '', hydrated: true })
  },
  openApiKeyModal: (reason = '') => {
    set({ apiKeyModalOpen: true, apiKeyModalReason: reason })
  },
  closeApiKeyModal: () => {
    set({ apiKeyModalOpen: false })
  },
  hydrate: () => {
    set({
      temporaryDoubaoApiKey: readStoredTemporaryDoubaoApiKey(),
      hydrated: true,
    })
  },
}))

export const getTemporaryDoubaoApiKey = () => readStoredTemporaryDoubaoApiKey()
