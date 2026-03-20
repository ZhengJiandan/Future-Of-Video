import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RequireAuth } from './components/RequireAuth'
import { MainLayout } from './layouts/MainLayout'
import { CharacterLibraryListPage } from './pages/CharacterLibraryListPage'
import { HomePage } from './pages/HomePage'
import { CharacterLibraryPage } from './pages/CharacterLibraryPage'
import { LoginPage } from './pages/LoginPage'
import { ProjectListPage } from './pages/ProjectListPage'
import { SceneLibraryListPage } from './pages/SceneLibraryListPage'
import { SceneLibraryPage } from './pages/SceneLibraryPage'
import { ScriptPipelinePage } from './pages/ScriptPipelinePage'
import { VoiceCatalogPage } from './pages/VoiceCatalogPage'

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    element: <RequireAuth />,
    children: [
      {
        path: '/',
        element: <MainLayout />,
        children: [
          {
            index: true,
            element: <HomePage />,
          },
          {
            path: 'script-pipeline',
            element: <ScriptPipelinePage />,
          },
          {
            path: 'projects',
            element: <ProjectListPage />,
          },
          {
            path: 'characters',
            element: <CharacterLibraryPage />,
          },
          {
            path: 'characters/library',
            element: <CharacterLibraryListPage />,
          },
          {
            path: 'scenes',
            element: <SceneLibraryPage />,
          },
          {
            path: 'scenes/library',
            element: <SceneLibraryListPage />,
          },
          {
            path: 'voices',
            element: <VoiceCatalogPage />,
          },
        ],
      },
    ],
  },
  {
    path: '*',
    element: <Navigate to="/script-pipeline" replace />,
  },
])
