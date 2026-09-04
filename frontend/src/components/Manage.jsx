import { useEffect, useState } from 'react'

const BASE = '/api'

async function fetchAuthStatus() {
  const res = await fetch(`${BASE}/auth/status`)
  return res.json()
}

async function postSession(bearer_token) {
  const res = await fetch(`${BASE}/auth/session`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bearer_token }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail)
  }
  return res.json()
}

async function logout() {
  await fetch(`${BASE}/auth/session`, { method: 'DELETE' })
}

async function fetchRecommendations() {
  const res = await fetch(`${BASE}/manage/recommendations`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail)
  }
  return res.json()
}

async function confirmTransfers(transfers, chip = null) {
  const res = await fetch(`${BASE}/manage/transfers/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ transfers, chip }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail)
  }
  return res.json()
}

async function fetchSquadBuild(budget) {
  const res = await fetch(`${BASE}/manage/build-squad?budget=${budget}`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail)
  }
  return res.json()
}

async function confirmCaptain(captainId, viceCaptainId) {
  const res = await fetch(`${BASE}/manage/captain/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ captain_id: captainId, vice_captain_id: viceCaptainId }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail)
  }
  return res.json()
}

// ---------------------------------------------------------------------------
// Squad builder panel
// ---------------------------------------------------------------------------

const POS_ORDER = ['GKP', 'DEF', 'MID', 'FWD']
const POS_COLOUR = { GKP: 'text-yellow-400', DEF: 'text-blue-400', MID: 'text-green-400', FWD: 'text-red-400' }

function SquadBuildPanel({ data, budget, onBack }) {
  const { squad = [], formation, total_cost_millions, remaining_budget_millions, summary, _budget_warning } = data
  const captainId = data.captain_id
  const vcId = data.vice_captain_id

  const starters = squad.filter(p => p.is_starter)
  const bench = squad.filter(p => !p.is_starter)

  function byPos(list) {
    const grouped = {}
    for (const pos of POS_ORDER) grouped[pos] = list.filter(p => p.position === pos)
    return grouped
  }

  const startersByPos = byPos(starters)

  return (
    <div className="p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-lg">Suggested Squad</h2>
        <button onClick={onBack} className="text-xs text-gray-500 hover:text-gray-300">← Back</button>
      </div>

      {/* Summary */}
      <div className="bg-gray-800/60 rounded-xl p-4 space-y-2">
        <p className="text-sm text-gray-300 leading-relaxed">{summary}</p>
        <div className="flex flex-wrap gap-4 text-xs text-gray-400 pt-1">
          <span>Budget: £{budget}m</span>
          <span>Total cost: £{total_cost_millions}m</span>
          <span className={remaining_budget_millions < 0 ? 'text-red-400' : 'text-green-400'}>
            Remaining: £{remaining_budget_millions}m
          </span>
          {formation && <span>Formation: {formation}</span>}
        </div>
        {_budget_warning && <p className="text-xs text-yellow-400">{_budget_warning}</p>}
      </div>

      {/* Starters */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">Starting XI</h3>
        <div className="space-y-1">
          {POS_ORDER.filter(pos => startersByPos[pos]?.length).map(pos => (
            <div key={pos}>
              {startersByPos[pos].map((p, i) => (
                <div key={i} className="bg-gray-800 rounded-lg px-3 py-2 flex items-center gap-3 mb-1">
                  <span className={`text-xs font-bold w-8 ${POS_COLOUR[pos]}`}>{pos}</span>
                  <span className="font-medium text-sm flex-1">{p.name}</span>
                  {p.player_id === captainId && <span className="text-xs bg-yellow-600 text-white rounded px-1.5 py-0.5 font-bold">C</span>}
                  {p.player_id === vcId && <span className="text-xs bg-gray-600 text-white rounded px-1.5 py-0.5 font-bold">VC</span>}
                  <span className="text-xs text-gray-400">{p.team}</span>
                  <span className="text-xs text-gray-400">£{p.cost_millions}m</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Bench */}
      {bench.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">Bench</h3>
          <div className="space-y-1">
            {bench.map((p, i) => (
              <div key={i} className="bg-gray-800/50 rounded-lg px-3 py-2 flex items-center gap-3">
                <span className={`text-xs font-bold w-8 ${POS_COLOUR[p.position]}`}>{p.position}</span>
                <span className="font-medium text-sm flex-1 text-gray-400">{p.name}</span>
                <span className="text-xs text-gray-500">{p.team}</span>
                <span className="text-xs text-gray-500">£{p.cost_millions}m</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Per-player reasoning */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">Why these picks</h3>
        <div className="space-y-1">
          {squad.map((p, i) => p.reasoning && (
            <div key={i} className="flex gap-2 text-xs text-gray-400">
              <span className="font-medium text-gray-300 shrink-0">{p.name}:</span>
              <span>{p.reasoning}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Session login form
// ---------------------------------------------------------------------------

function SessionForm({ onLogin }) {
  const [token, setToken] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handle() {
    if (!token.trim()) return
    setLoading(true)
    setError(null)
    try {
      await postSession(token.trim())
      onLogin(token.trim())
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-4 max-w-lg">
      <h2 className="font-semibold text-lg mb-1">Connect to FPL</h2>
      <p className="text-sm text-gray-400 mb-1">
        Your token is stored in memory only and never saved to disk.
      </p>
      <p className="text-sm text-gray-400 mb-4">
        To get it: log into <strong>fantasy.premierleague.com</strong>, open DevTools
        (F12) → <strong>Network</strong> tab → filter <strong>Fetch/XHR</strong> → refresh the page →
        click any <code className="text-violet-300">/api/</code> request → <strong>Request Headers</strong> →
        copy the value of <code className="text-violet-300">x-api-authorization</code> (everything after "Bearer ").
      </p>

      <div className="space-y-3">
        <div>
          <label className="text-xs text-gray-400 block mb-1">x-api-authorization token</label>
          <textarea
            className="w-full bg-gray-800 text-gray-100 rounded-lg px-3 py-2 text-xs font-mono resize-none focus:outline-none focus:ring-1 focus:ring-violet-500"
            rows={4}
            placeholder="Paste the JWT token (or the full 'Bearer eyJ…' value)…"
            value={token}
            onChange={e => setToken(e.target.value)}
          />
        </div>
        {error && <p className="text-red-400 text-sm">{error}</p>}
        <button
          onClick={handle}
          disabled={loading || !token.trim()}
          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
        >
          {loading ? 'Validating…' : 'Connect'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Recommendations panel
// ---------------------------------------------------------------------------

function TransferCard({ transfer, onConfirm, confirming }) {
  function buildTransferPayload() {
    return [{
      element_in: transfer.in_player_id,
      element_out: transfer.out_player_id,
    }]
  }

  return (
    <div className="bg-gray-800 rounded-xl p-4 space-y-2">
      <div className="flex items-center gap-2 text-sm flex-wrap">
        <span className="text-red-400 font-semibold">OUT</span>
        <span className="font-medium">{transfer.out_player_name}</span>
        <span className="text-gray-500 text-xs">£{transfer.out_selling_price_millions}m</span>
        <span className="mx-1 text-gray-500">→</span>
        <span className="text-green-400 font-semibold">IN</span>
        <span className="font-medium">{transfer.in_player_name}</span>
        <span className="text-gray-500 text-xs">£{transfer.in_cost_millions}m</span>
      </div>
      <p className="text-xs text-gray-400 leading-relaxed">{transfer.reasoning}</p>
      <button
        onClick={() => onConfirm(buildTransferPayload())}
        disabled={confirming}
        className="text-xs bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded-lg px-3 py-1.5 font-medium transition-colors"
      >
        {confirming ? 'Submitting…' : 'Confirm Transfer'}
      </button>
    </div>
  )
}

function RecommendationsPanel({ data, onLogout }) {
  const { recommendations: recs, free_transfers } = data
  const [confirming, setConfirming] = useState(null)
  const [confirmed, setConfirmed] = useState([])
  const [captainDone, setCaptainDone] = useState(false)
  const [error, setError] = useState(null)

  async function handleTransferConfirm(transfers, chip = null) {
    setConfirming('transfer')
    setError(null)
    try {
      await confirmTransfers(transfers, chip)
      setConfirmed(prev => [...prev, transfers[0].element_in])
    } catch (err) {
      setError(err.message)
    } finally {
      setConfirming(null)
    }
  }

  async function handleCaptainConfirm() {
    setConfirming('captain')
    setError(null)
    try {
      await confirmCaptain(recs.captain.player_id, recs.vice_captain.player_id)
      setCaptainDone(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setConfirming(null)
    }
  }

  return (
    <div className="p-4 space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-lg">GW Recommendations</h2>
        <button onClick={onLogout} className="text-xs text-gray-500 hover:text-gray-300">
          Disconnect
        </button>
      </div>

      {/* Summary */}
      <div className="bg-gray-800/60 rounded-xl p-4 space-y-2">
        <p className="text-sm text-gray-300 leading-relaxed">{recs.summary}</p>
        <p className="text-xs text-gray-500">{free_transfers} free transfer{free_transfers !== 1 ? 's' : ''} available</p>
        {recs.budget_check && (
          <p className="text-xs text-gray-400">
            Bank £{recs.budget_check.bank_millions}m · Sold £{recs.budget_check.total_sold_millions}m · Bought £{recs.budget_check.total_bought_millions}m · Remaining £{recs.budget_check.remaining_bank_millions}m
          </p>
        )}
        {recs._budget_warning && (
          <p className="text-xs text-yellow-400 font-medium">{recs._budget_warning}</p>
        )}
        {recs._duplicate_warning && (
          <p className="text-xs text-yellow-400 font-medium">{recs._duplicate_warning}</p>
        )}
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {/* Captain */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">Captain</h3>
        <div className="bg-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-yellow-400 font-bold text-lg">C</span>
            <span className="font-semibold">{recs.captain.player_name}</span>
            <span className="text-gray-500 text-sm">/ VC: {recs.vice_captain.player_name}</span>
          </div>
          <p className="text-xs text-gray-400 leading-relaxed">{recs.captain.reasoning}</p>
          {captainDone ? (
            <p className="text-xs text-green-400 font-medium">Captain updated</p>
          ) : (
            <button
              onClick={handleCaptainConfirm}
              disabled={confirming === 'captain'}
              className="text-xs bg-yellow-600 hover:bg-yellow-500 disabled:opacity-50 text-white rounded-lg px-3 py-1.5 font-medium transition-colors"
            >
              {confirming === 'captain' ? 'Updating…' : 'Confirm Captain'}
            </button>
          )}
        </div>
      </div>

      {/* Transfers */}
      {recs.transfers.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">
            Transfers
          </h3>
          <div className="space-y-3">
            {recs.transfers.map((t, i) => (
              confirmed.includes(t.in_player_id) ? (
                <div key={i} className="bg-gray-800 rounded-xl p-4">
                  <p className="text-xs text-green-400 font-medium">
                    Transfer confirmed: {t.out_player_name} → {t.in_player_name}
                  </p>
                </div>
              ) : (
                <TransferCard
                  key={i}
                  transfer={t}
                  onConfirm={transfers => handleTransferConfirm(transfers, recs.chip?.name)}
                  confirming={confirming === 'transfer'}
                />
              )
            ))}
          </div>
        </div>
      )}

      {recs.transfers.length === 0 && (
        <div className="bg-gray-800/60 rounded-xl p-4">
          <p className="text-sm text-gray-400">No transfers recommended this week.</p>
        </div>
      )}

      {/* Chip */}
      {recs.chip?.name && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-2">Chip</h3>
          <div className="bg-gray-800 rounded-xl p-4">
            <span className="text-xs bg-violet-700 text-white rounded px-2 py-0.5 font-bold uppercase mr-2">
              {recs.chip.name}
            </span>
            <p className="text-xs text-gray-400 mt-2 leading-relaxed">{recs.chip.reasoning}</p>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Manage component
// ---------------------------------------------------------------------------

const TOKEN_KEY = 'fpl_bearer_token'

export default function Manage() {
  const [authStatus, setAuthStatus] = useState(null)   // null = loading
  const [recData, setRecData] = useState(null)
  const [loadingRecs, setLoadingRecs] = useState(false)
  const [squadData, setSquadData] = useState(null)
  const [loadingSquad, setLoadingSquad] = useState(false)
  const [budget, setBudget] = useState('100.0')
  const [error, setError] = useState(null)

  useEffect(() => {
    async function init() {
      // Try to restore token from localStorage
      const stored = localStorage.getItem(TOKEN_KEY)
      if (stored) {
        try {
          const res = await postSession(stored)
          setAuthStatus({ authenticated: true, ...res })
          return
        } catch {
          // Token expired or invalid — clear it and show login form
          localStorage.removeItem(TOKEN_KEY)
        }
      }
      const status = await fetchAuthStatus()
      setAuthStatus(status)
    }
    init()
  }, [])

  async function handleLogin(token) {
    localStorage.setItem(TOKEN_KEY, token)
    const status = await fetchAuthStatus()
    setAuthStatus(status)
  }

  async function handleLogout() {
    localStorage.removeItem(TOKEN_KEY)
    await logout()
    setAuthStatus({ authenticated: false })
    setRecData(null)
  }

  async function handleLoadRecs() {
    setLoadingRecs(true)
    setError(null)
    try {
      const data = await fetchRecommendations()
      setRecData(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingRecs(false)
    }
  }

  async function handleBuildSquad() {
    setLoadingSquad(true)
    setError(null)
    try {
      const data = await fetchSquadBuild(parseFloat(budget) || 100.0)
      setSquadData(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingSquad(false)
    }
  }

  if (authStatus === null) {
    return <div className="p-4 text-gray-500 text-sm">Checking session…</div>
  }

  if (!authStatus.authenticated) {
    return <SessionForm onLogin={handleLogin} />
  }

  if (recData) {
    return <RecommendationsPanel data={recData} onLogout={handleLogout} />
  }

  if (squadData) {
    return <SquadBuildPanel data={squadData} budget={parseFloat(budget)} onBack={() => setSquadData(null)} />
  }

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-lg">Team Management</h2>
          <p className="text-xs text-green-400 mt-0.5">
            Connected · expires {authStatus.expires_at ? new Date(authStatus.expires_at).toLocaleTimeString() : 'unknown'}
          </p>
        </div>
        <button onClick={handleLogout} className="text-xs text-gray-500 hover:text-gray-300">
          Disconnect
        </button>
      </div>

      <p className="text-sm text-gray-400">
        Claude will analyse your squad, the upcoming fixtures, and the transfer market
        to recommend transfers and a captain pick. You confirm before anything is submitted.
      </p>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      <button
        onClick={handleLoadRecs}
        disabled={loadingRecs}
        className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 text-white rounded-xl px-5 py-2.5 text-sm font-medium transition-colors"
      >
        {loadingRecs ? (
          <span className="flex items-center gap-2">
            <span className="animate-spin inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
            Analysing your squad…
          </span>
        ) : (
          'Get Recommendations'
        )}
      </button>

      {/* Squad builder */}
      <div className="border-t border-gray-800 pt-4 space-y-3">
        <div>
          <h3 className="font-medium text-sm text-gray-200">Build New Squad</h3>
          <p className="text-xs text-gray-500 mt-0.5">
            Claude picks the best 15-player squad within your budget — useful for wildcard or free hit planning.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Budget (£m)</label>
            <input
              type="number"
              min="50"
              max="120"
              step="0.1"
              value={budget}
              onChange={e => setBudget(e.target.value)}
              className="w-24 bg-gray-800 text-gray-100 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500"
            />
          </div>
          <button
            onClick={handleBuildSquad}
            disabled={loadingSquad}
            className="mt-5 bg-green-700 hover:bg-green-600 disabled:opacity-50 text-white rounded-xl px-5 py-2 text-sm font-medium transition-colors"
          >
            {loadingSquad ? (
              <span className="flex items-center gap-2">
                <span className="animate-spin inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
                Building…
              </span>
            ) : (
              'Build Squad'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
