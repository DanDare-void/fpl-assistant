import { useEffect, useState } from 'react'
import { fetchFdr } from '../api'

const FDR_COLOURS = {
  1: 'bg-green-700',
  2: 'bg-green-500',
  3: 'bg-gray-600',
  4: 'bg-orange-500',
  5: 'bg-red-600',
}

function FdrCell({ fixture }) {
  if (!fixture) return <td className="w-12 px-1 py-1.5" />
  const bg = FDR_COLOURS[fixture.fdr] ?? 'bg-gray-700'
  const label = fixture.home ? fixture.opponent : fixture.opponent.toLowerCase()
  return (
    <td className="px-1 py-1.5 text-center">
      <span
        className={`inline-block rounded text-[10px] font-bold px-1.5 py-0.5 w-10 text-center ${bg} text-white`}
        title={`GW${fixture.gw} vs ${fixture.opponent} (${fixture.home ? 'H' : 'A'}) FDR ${fixture.fdr}`}
      >
        {label}
      </span>
    </td>
  )
}

export default function Fixtures() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchFdr(6)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="p-4 text-gray-500 text-sm">Loading fixtures…</div>
  if (error) return <div className="p-4 text-red-400 text-sm">{error}</div>
  if (!data) return null

  // Sort teams by average FDR across next 3 GWs (easiest first)
  const teams = [...data.teams].sort((a, b) => {
    const avgA = a.fixtures.slice(0, 3).reduce((s, f) => s + f.fdr, 0) / 3 || 5
    const avgB = b.fixtures.slice(0, 3).reduce((s, f) => s + f.fdr, 0) / 3 || 5
    return avgA - avgB
  })

  // Collect gameweek numbers for header
  const gwNumbers = [...new Set(
    teams.flatMap(t => t.fixtures.map(f => f.gw))
  )].sort((a, b) => a - b).slice(0, 6)

  return (
    <div className="p-4">
      <h2 className="font-semibold text-lg mb-3">Fixture Difficulty (Next 6 GWs)</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              <th className="text-left text-xs text-gray-400 font-medium pb-2 pr-2 w-12">Team</th>
              {gwNumbers.map(gw => (
                <th key={gw} className="text-center text-xs text-gray-400 font-medium pb-2 w-12">
                  GW{gw}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {teams.map(team => {
              const byGw = Object.fromEntries(team.fixtures.map(f => [f.gw, f]))
              return (
                <tr key={team.team_id} className="hover:bg-gray-800/40">
                  <td className="pr-2 py-1 text-xs font-semibold text-gray-300 whitespace-nowrap">
                    {team.team}
                  </td>
                  {gwNumbers.map(gw => (
                    <FdrCell key={gw} fixture={byGw[gw]} />
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {/* Legend */}
      <div className="flex gap-3 mt-4 flex-wrap text-[11px] text-gray-400">
        {Object.entries(FDR_COLOURS).map(([fdr, bg]) => (
          <span key={fdr} className="flex items-center gap-1">
            <span className={`inline-block w-3 h-3 rounded-sm ${bg}`} />
            FDR {fdr}
          </span>
        ))}
        <span className="ml-2 italic">H = home, lowercase = away</span>
      </div>
    </div>
  )
}
