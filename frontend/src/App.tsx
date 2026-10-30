import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { HistoryScreen } from './screens/HistoryScreen'
import { SetupScreen } from './screens/SetupScreen'
import { WelcomeScreen } from './screens/WelcomeScreen'

const StudioScreen = lazy(() =>
  import('./screens/StudioScreen').then((module) => ({ default: module.StudioScreen })),
)
const ExperimentsScreen = lazy(() =>
  import('./screens/ExperimentsScreen').then((module) => ({ default: module.ExperimentsScreen })),
)
const CompareScreen = lazy(() =>
  import('./screens/CompareScreen').then((module) => ({ default: module.CompareScreen })),
)
const PhysicalLabScreen = lazy(() =>
  import('./screens/PhysicalLabScreen').then((module) => ({ default: module.PhysicalLabScreen })),
)
const VisualCatalogScreen = lazy(() =>
  import('./screens/VisualCatalogScreen').then((module) => ({ default: module.VisualCatalogScreen })),
)

function RouteLoading() {
  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        color: 'var(--text-2)',
        fontSize: 12,
      }}
    >
      Loading…
    </div>
  )
}

function StudioRoute() {
  const { runId } = useParams<{ runId: string }>()
  // Studio owns live data, attempt history and playback for one launch.
  return <StudioScreen key={runId} />
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<RouteLoading />}>
        <Routes>
          <Route path="/" element={<WelcomeScreen />} />
          <Route path="/setup" element={<SetupScreen />} />
          <Route path="/studio/:runId" element={<StudioRoute />} />
          <Route path="/history" element={<HistoryScreen />} />
          <Route path="/experiments" element={<ExperimentsScreen />} />
          <Route path="/compare" element={<CompareScreen />} />
          <Route path="/physical" element={<PhysicalLabScreen />} />
          <Route path="/visuals" element={<VisualCatalogScreen />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
