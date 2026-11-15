import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router'
import { AiChatProvider } from '../../context/AiChatProvider'
import { AiChat } from '../ai/AiChat'
import { Footer } from './Footer'
import { Navbar } from './Navbar'

export function Layout() {
  const { pathname } = useLocation()
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [pathname])

  return (
    <AiChatProvider>
      <div className="flex min-h-screen flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[2000] btn-primary">
          Skip to content
        </a>
        <Navbar />
        <main id="main" className="flex-1">
          <Outlet />
        </main>
        <Footer />
        {/* Mounted at layout level: the conversation survives client-side route changes. */}
        <AiChat />
      </div>
    </AiChatProvider>
  )
}
