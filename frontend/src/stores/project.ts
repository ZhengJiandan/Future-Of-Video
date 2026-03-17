import { create } from 'zustand'

const PROJECT_STORAGE_KEY = 'pipeline_selected_project'

interface ProjectState {
  currentProjectId: string | null
  hydrated: boolean
  setCurrentProjectId: (projectId: string | null) => void
  clearCurrentProjectId: () => void
  hydrate: () => void
}

const readStoredProjectId = () => {
  if (typeof window === 'undefined') {
    return null
  }
  return window.localStorage.getItem(PROJECT_STORAGE_KEY)
}

const persistProjectId = (projectId: string | null) => {
  if (typeof window === 'undefined') {
    return
  }

  if (!projectId) {
    window.localStorage.removeItem(PROJECT_STORAGE_KEY)
    return
  }

  window.localStorage.setItem(PROJECT_STORAGE_KEY, projectId)
}

export const useProjectStore = create<ProjectState>((set) => ({
  currentProjectId: null,
  hydrated: false,
  setCurrentProjectId: (projectId) => {
    persistProjectId(projectId)
    set({ currentProjectId: projectId, hydrated: true })
  },
  clearCurrentProjectId: () => {
    persistProjectId(null)
    set({ currentProjectId: null, hydrated: true })
  },
  hydrate: () => {
    set({ currentProjectId: readStoredProjectId(), hydrated: true })
  },
}))
