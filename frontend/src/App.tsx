import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router'
import { LoadingState } from './components/common/States'
import { Layout } from './components/layout/Layout'
import Home from './pages/Home'

// Heavier pages (map, charts) are code-split so the landing page loads quickly.
const Explore = lazy(() => import('./pages/Explore'))
const Results = lazy(() => import('./pages/Results'))
const Learn = lazy(() => import('./pages/Learn'))
const Compare = lazy(() => import('./pages/Compare'))
const RegionalExplore = lazy(() => import('./pages/RegionalExplore'))
const RegionalResults = lazy(() => import('./pages/RegionalResults'))
const NotFound = lazy(() => import('./pages/NotFound'))
const AnalysisJobs = lazy(() => import('./pages/AnalysisJobs'))
const JobDetails = lazy(() => import('./pages/JobDetails'))

function PageFallback() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <LoadingState title="Loading…" />
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="explore" element={<Explore />} />
            <Route path="results" element={<Results />} />
            <Route path="compare" element={<Compare />} />
            <Route path="regional" element={<RegionalExplore />} />
            <Route path="regional/results" element={<RegionalResults />} />
            <Route path="jobs" element={<AnalysisJobs />} />
            <Route path="jobs/:jobId" element={<JobDetails />} />
            <Route path="learn" element={<Learn />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
