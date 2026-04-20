import { useState } from 'react'
import Chat from './components/Chat'
import SquadView from './components/SquadView'
import Fixtures from './components/Fixtures'
import ReportPanel from './components/ReportPanel'
import Manage from './components/Manage'
import Admin from './components/Admin'

const TABS = [
  { id: 'chat',     label: 'Chat' },
  { id: 'squad',    label: 'Squad' },
  { id: 'fixtures', label: 'Fixtures' },
  { id: 'report',   label: 'Report' },
  { id: 'manage',   label: 'Manage' },
  { id: 'admin',    label: 'Admin' },
]

export default function App() {
  const [tab, setTab] = useState('chat')

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl">⚽</span>
          <span className="font-bold text-lg tracking-tight">FPL Assistant</span>
        </div>
        <span className="text-xs text-gray-500">Powered by Claude</span>
      </header>

      {/* Tab bar */}
      <nav className="border-b border-gray-800 px-4 flex gap-1">
        {TABS.map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t.id
                ? 'border-violet-500 text-violet-400'
                : 'border-transparent text-gray-400 hover:text-gray-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {/* Panel */}
      <main className="flex-1 overflow-hidden flex flex-col max-w-3xl w-full mx-auto">
        {tab === 'chat'     && <Chat />}
        {tab === 'squad'    && <div className="flex-1 overflow-y-auto"><SquadView /></div>}
        {tab === 'fixtures' && <div className="flex-1 overflow-y-auto"><Fixtures /></div>}
        {tab === 'report'   && <div className="flex-1 overflow-y-auto"><ReportPanel /></div>}
        {tab === 'manage'   && <div className="flex-1 overflow-y-auto"><Manage /></div>}
        {tab === 'admin'    && <div className="flex-1 overflow-y-auto"><Admin /></div>}
      </main>
    </div>
  )
}
