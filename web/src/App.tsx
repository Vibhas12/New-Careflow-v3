import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useMe } from './api/hooks'
import type { User } from './api/types'
import { Layout } from './components/Layout'
import { Loading } from './components/ui'
import { AppointmentsPage } from './pages/AppointmentsPage'
import { AssistantPage } from './pages/AssistantPage'
import { CareGapsPage } from './pages/CareGapsPage'
import { ImportPage } from './pages/ImportPage'
import { ComingSoonPage } from './pages/ComingSoonPage'
import { ExecutivePage, PerformancePage } from './pages/MetricsPages'
import { TasksPage } from './pages/TasksPage'
import { TestsPage } from './pages/TestsPage'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { PatientDetailPage } from './pages/PatientDetailPage'
import { PatientsPage } from './pages/PatientsPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/*" element={<Authenticated />} />
    </Routes>
  )
}

/** Everything except /login requires a session. Role checks here are for UX only – the API enforces them. */
function Authenticated() {
  const me = useMe()
  const loc = useLocation()
  if (me.isLoading) return <Loading />
  if (!me.data) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  const user: User = me.data
  const clinical = user.role !== 'admin'
  return (
    <Routes>
      <Route element={<Layout user={user} />}>
        <Route index element={<DashboardPage user={user} />} />
        {clinical && <Route path="patients" element={<PatientsPage user={user} />} />}
        {clinical && <Route path="patients/:id" element={<PatientDetailPage />} />}
        <Route path="appointments" element={<AppointmentsPage user={user} />} />
        {clinical && <Route path="tests" element={<TestsPage user={user} />} />}
        <Route path="tasks" element={<TasksPage user={user} />} />
        <Route path="care-gaps" element={<CareGapsPage user={user} />} />
        {clinical && <Route path="assistant" element={<AssistantPage />} />}
        {user.role === 'coordinator' && <Route path="import" element={<ImportPage />} />}
        {user.role !== 'coordinator' && <Route path="performance" element={<PerformancePage user={user} />} />}
        {user.role === 'admin' && <Route path="executive" element={<ExecutivePage />} />}
        <Route path="*" element={<ComingSoonPage />} />
      </Route>
    </Routes>
  )
}
