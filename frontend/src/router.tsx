import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RequireAuth } from './components/RequireAuth'
import { MainLayout } from './layouts/MainLayout'
import { CharacterLibraryListPage } from './pages/CharacterLibraryListPage'
import { HomePage } from './pages/HomePage'
import { CharacterLibraryPage } from './pages/CharacterLibraryPage'
import { LoginPage } from './pages/LoginPage'
import { CharacterSubjectPage } from './pages/CharacterSubjectPage'
import { CharacterVoicePage } from './pages/CharacterVoicePage'
import { ProjectListPage } from './pages/ProjectListPage'
import { SceneLibraryListPage } from './pages/SceneLibraryListPage'
import { SceneLibraryPage } from './pages/SceneLibraryPage'
import { ScriptPipelinePage } from './pages/ScriptPipelinePage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      {
        index: true,
        element: <HomePage />,
      },
      {
        element: <RequireAuth />,
        children: [
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
            element: <Navigate to="/characters/subjects" replace />,
          },
          {
            path: 'characters/subjects',
            element: <CharacterSubjectPage />,
          },
          {
            path: 'characters/new',
            element: <CharacterLibraryPage />,
          },
          {
            path: 'characters/edit',
            element: <CharacterLibraryPage />,
          },
          {
            path: 'characters/library',
            element: <CharacterLibraryListPage />,
          },
          {
            path: 'characters/voices',
            element: <CharacterVoicePage />,
          },
          {
            path: 'scenes',
            element: <Navigate to="/scenes/library" replace />,
          },
          {
            path: 'scenes/new',
            element: <SceneLibraryPage />,
          },
          {
            path: 'scenes/edit',
            element: <SceneLibraryPage />,
          },
          {
            path: 'scenes/library',
            element: <SceneLibraryListPage />,
          },
        ],
      },
    ],
  },
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
