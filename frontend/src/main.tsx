import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import LoginPage from './pages/Login'
import Dashboard from './pages/Dashboard'
import Accounts from './pages/Accounts'
import Campaigns from './pages/Campaigns'
import CampaignDetail from './pages/CampaignDetail'
import Leads from './pages/Leads'
import Threads from './pages/Threads'
import Jobs from './pages/Jobs'
import Settings from './pages/Settings'

const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  { path: '/', element: <Dashboard /> },
  { path: '/accounts', element: <Accounts /> },
  { path: '/campaigns', element: <Campaigns /> },
  { path: '/campaigns/:id', element: <CampaignDetail /> },
  { path: '/leads', element: <Leads /> },
  { path: '/threads', element: <Threads /> },
  { path: '/jobs', element: <Jobs /> },
  { path: '/settings', element: <Settings /> },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
