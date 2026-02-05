import { useEffect, useState } from 'react'

interface ModelPricing {
  model_id: string
  input_price_per_1k: number
  output_price_per_1k: number
  description?: string
}

export default function Pricing() {
  const [pricing, setPricing] = useState<ModelPricing[]>([])
  const [loading, setLoading] = useState(true)
  const [estimate, setEstimate] = useState({
    model_id: 'claude-sonnet-4-5-20250929',
    prompt_tokens: 1000,
    completion_tokens: 500,
  })
  const [cost, setCost] = useState<any>(null)

  useEffect(() => {
    fetch('/api/pricing')
      .then((res) => res.json())
      .then((data) => {
        setPricing(data.pricing || [])
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  const calculateCost = async () => {
    try {
      const params = new URLSearchParams({
        model_id: estimate.model_id,
        prompt_tokens: estimate.prompt_tokens.toString(),
        completion_tokens: estimate.completion_tokens.toString(),
      })
      const res = await fetch(`/api/pricing/cost-estimate?${params}`)
      const data = await res.json()
      setCost(data)
    } catch {
      alert('Failed to calculate cost')
    }
  }

  if (loading) {
    return <div className="text-center py-10">Loading...</div>
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Model Pricing</h2>

      {/* Pricing Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden mb-8">
        <table className="w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Model
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Description
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Input ($/1K tokens)
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                Output ($/1K tokens)
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {pricing.map((p) => (
              <tr key={p.model_id}>
                <td className="px-6 py-4 font-mono text-sm">{p.model_id}</td>
                <td className="px-6 py-4">{p.description}</td>
                <td className="px-6 py-4">${p.input_price_per_1k.toFixed(4)}</td>
                <td className="px-6 py-4">${p.output_price_per_1k.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Cost Calculator */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-bold mb-4">Cost Calculator</h3>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
          <div>
            <label className="block text-gray-700 mb-2">Model</label>
            <select
              value={estimate.model_id}
              onChange={(e) => setEstimate({ ...estimate, model_id: e.target.value })}
              className="w-full px-3 py-2 border rounded"
            >
              {pricing.map((p) => (
                <option key={p.model_id} value={p.model_id}>
                  {p.model_id}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-gray-700 mb-2">Prompt Tokens</label>
            <input
              type="number"
              value={estimate.prompt_tokens}
              onChange={(e) =>
                setEstimate({ ...estimate, prompt_tokens: parseInt(e.target.value) })
              }
              className="w-full px-3 py-2 border rounded"
            />
          </div>
          <div>
            <label className="block text-gray-700 mb-2">Completion Tokens</label>
            <input
              type="number"
              value={estimate.completion_tokens}
              onChange={(e) =>
                setEstimate({ ...estimate, completion_tokens: parseInt(e.target.value) })
              }
              className="w-full px-3 py-2 border rounded"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={calculateCost}
              className="w-full bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
            >
              Calculate
            </button>
          </div>
        </div>

        {cost && (
          <div className="bg-gray-50 p-4 rounded">
            <div className="grid grid-cols-3 gap-4 text-center">
              <div>
                <p className="text-gray-500 text-sm">Input Cost</p>
                <p className="text-xl font-bold">${cost.input_cost_usd.toFixed(6)}</p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Output Cost</p>
                <p className="text-xl font-bold">${cost.output_cost_usd.toFixed(6)}</p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Total Cost</p>
                <p className="text-xl font-bold text-blue-600">
                  ${cost.total_cost_usd.toFixed(6)}
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
