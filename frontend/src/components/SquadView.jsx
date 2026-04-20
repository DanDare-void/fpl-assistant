import { useEffect, useState } from 'react'
import { fetchSquad } from '../api'

const STATUS_COLOURS = {
  a: 'bg-green-500',
  d: 'bg-yellow-400',
  i: 'bg-red-500',
  s: 'bg-red-600',
  u: 'bg-gray-500',
}

const FDR_COLOURS = {
  1: 'bg-green-700 text-green-100',
  2: 'bg-green-600 text-green-100',
  3: 'bg-gray-600 text-gray-100',
  4: 'bg-orange-600 text-orange-100',
  5: 'bg-red-700 text-red-100',
}

function FixturePip({ fixture }) {
  const colour = FDR_COLOURS[fixture.fdr] ?? 'bg-gray-700'
  return (
    <span
      className={`inline-block rounded px-1 py-0.5 text-[10px] font-bold mr-0.5 ${colour}`}
      title={`GW${fixture.gw} vs ${fixture.opponent} (${fixture.home ? 'H' : 'A'})`}
    >
      {fixture.opponent}
    </span>
  )
}

function PlayerRow({ player }) {
  const statusDot = STATUS_COLOURS[player.status] ?? 'bg-gray-500'
  const isCap = player.is_captain
  const isVice = player.is_vice_captain

  return (
    <div className="flex items-center gap-3 py-2 px-3 hover:bg-gray-800/60 rounded-lg">
      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot}`} title={player.news || player.status} />
      <span className="w-8 text-[10px] font-medium text-gray-400 uppercase">{player.position}</span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-sm font-medium truncate">{player.name}</span>
          {isCap && <span className="text-[10px] bg-yellow-500 text-black rounded px-1 font-bold">C</span>}
          {isVice && <span className="text-[10px] bg-gray-600 text-white rounded px-1 font-bold">V</span>}
        </div>
        <div className="text-[11px] text-gray-400">{player.team}</div>
      </div>
      <div className="text-right text-[11px] text-gray-400 hidden sm:block">
        {player.upcoming_fixtures?.slice(0, 3).map((f, i) => (
          <FixturePip key={i} fixture={f} />
        ))}
      </div>
      <div className="text-right w-12">
        <div className="text-sm font-semibold">£{player.cost?.toFixed(1)}m</div>
        <div className="text-[11px] text-gray-400">Fm {player.form?.toFixed(1)}</div>
      </div>
    </div>
  )
}

export default function SquadView() {
  const [squad, setSquad] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchSquad()
      .then(setSquad)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-4 text-gray-500 text-sm">Loading squad…</div>
  if (error) return <div className="p-4 text-red-400 text-sm">{error}</div>
  if (!squad) return null

  const starters = squad.players.filter(p => p.is_starter)
  const bench = squad.players.filter(p => !p.is_starter)

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-semibold text-lg">GW{squad.gameweek} Squad</h2>
          {squad.active_chip && (
            <span className="text-xs bg-violet-700 text-white rounded px-2 py-0.5 ml-2">{squad.active_chip}</span>
          )}
        </div>
        <div className="text-right text-sm text-gray-400">
          <div>Bank <span className="text-white font-medium">£{squad.bank?.toFixed(1)}m</span></div>
          <div>Value <span className="text-white font-medium">£{squad.squad_value?.toFixed(1)}m</span></div>
        </div>
      </div>

      {/* Starters */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-1">Starting XI</h3>
        <div className="space-y-0.5">
          {starters.map(p => <PlayerRow key={p.id} player={p} />)}
        </div>
      </div>

      {/* Bench */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-1">Bench</h3>
        <div className="space-y-0.5 opacity-70">
          {bench.map(p => <PlayerRow key={p.id} player={p} />)}
        </div>
      </div>

      {/* Transfers */}
      {squad.event_transfers > 0 && (
        <p className="text-xs text-yellow-400">
          {squad.event_transfers} transfer{squad.event_transfers > 1 ? 's' : ''} made this GW
          {squad.transfer_cost > 0 && ` (−${squad.transfer_cost}pt)`}
        </p>
      )}
    </div>
  )
}
