import React, { useState } from 'react';

interface ApimaticModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ApimaticModal: React.FC<ApimaticModalProps> = ({ isOpen, onClose }) => {
  const [activeTab, setActiveTab] = useState<'typescript' | 'python' | 'spec'>('typescript');
  const [copied, setCopied] = useState(false);

  if (!isOpen) return null;

  const tsCode = `// Install via APIMatic CodeGen: npm install @mymile/travel-sdk
import { MyMileClient } from '@mymile/travel-sdk';

const mymile = new MyMileClient({
  apiKey: process.env.MYMILE_API_KEY
});

// Execute AI Agent Travel Planning
const tripPlan = await mymile.trips.plan({
  destination: 'Kyoto, Japan',
  departureDate: '2026-04-08',
  returnDate: '2026-04-15',
  travelers: 2,
  purpose: 'Tourism',
  plan: 'premium',
  totalBudget: 4500
});

console.log('Match Score:', tripPlan.matchScore);
console.log('Recommended Stay:', tripPlan.recommendedHotel.name);
console.log('Channel3 Essentials:', tripPlan.travelEssentials.length);`;

  const pyCode = `# Install via APIMatic CodeGen: pip install mymile-travel-sdk
from mymile_travel_sdk import MyMileClient
import os

client = MyMileClient(api_key=os.getenv("MYMILE_API_KEY"))

# Execute AI Agent Travel Planning
trip = client.trips.plan(
    destination="Kyoto, Japan",
    departure_date="2026-04-08",
    return_date="2026-04-15",
    travelers=2,
    purpose="Tourism",
    plan="premium",
    total_budget=4500.0
)

print(f"Destination: {trip.destination}")
print(f"Weather: {trip.weather.current_condition}, {trip.weather.current_temp_c}°C")
print(f"Remaining Budget: \${trip.budget_breakdown.remaining_balance}")`;

  const copyCode = (code: string) => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/50 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-3xl max-w-2xl w-full shadow-2xl border border-slate-200 overflow-hidden flex flex-col">
        {/* Header */}
        <div className="p-6 bg-gradient-to-r from-blue-900 to-indigo-950 text-white flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="bg-yellow-400 text-gray-950 text-[11px] font-black px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                Sponsor Integration
              </span>
              <span className="text-blue-300 text-xs font-semibold">APIMatic Developer Platform</span>
            </div>
            <h2 className="text-xl font-black">APIMatic SDK & OpenAPI Hub</h2>
            <p className="text-xs text-blue-200 mt-1 max-w-md">
              MYMILE integrates APIMatic to transform its OpenAPI 3.0 specification into production-ready client SDKs and interactive API docs.
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-white/10 hover:bg-white/20 text-white flex items-center justify-center transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-4">
          <div className="flex gap-2 border-b border-gray-200 pb-2">
            <button
              onClick={() => setActiveTab('typescript')}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                activeTab === 'typescript'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              TypeScript SDK
            </button>
            <button
              onClick={() => setActiveTab('python')}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                activeTab === 'python'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              Python SDK
            </button>
            <button
              onClick={() => setActiveTab('spec')}
              className={`px-3 py-1.5 text-xs font-bold rounded-lg transition-all ${
                activeTab === 'spec'
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              OpenAPI 3.0 Specs
            </button>
          </div>

          {activeTab !== 'spec' ? (
            <div className="relative">
              <pre className="bg-slate-900 text-slate-100 p-4 rounded-xl text-xs font-mono overflow-x-auto leading-relaxed">
                {activeTab === 'typescript' ? tsCode : pyCode}
              </pre>
              <button
                onClick={() => copyCode(activeTab === 'typescript' ? tsCode : pyCode)}
                className="absolute top-3 right-3 bg-white/10 hover:bg-white/20 text-white text-[11px] font-bold px-2.5 py-1 rounded transition-colors"
              >
                {copied ? '✓ Copied' : 'Copy'}
              </button>
            </div>
          ) : (
            <div className="p-4 bg-slate-50 rounded-xl space-y-3 text-xs text-gray-700">
              <p className="font-semibold text-gray-900">
                APIMatic OpenAPI 3.0.3 Specification Endpoint:
              </p>
              <div className="flex items-center gap-2">
                <code className="bg-gray-200 px-2 py-1 rounded text-blue-700 font-bold flex-1">
                  /api/apimatic/openapi.json
                </code>
                <a
                  href="/api/apimatic/openapi.json"
                  target="_blank"
                  rel="noreferrer"
                  className="bg-blue-600 text-white px-3 py-1 rounded font-bold hover:bg-blue-700 transition-colors"
                >
                  View JSON ↗
                </a>
              </div>
              <p className="text-gray-500 text-[11px] leading-normal pt-1">
                Import this definition directly into APIMatic's Portal Dashboard to generate interactive code playgrounds and downloadable packages in 7+ languages.
              </p>
            </div>
          )}

          <div className="p-3 bg-yellow-50 border border-yellow-200 rounded-xl flex items-center justify-between text-xs text-yellow-900">
            <span>Official APIMatic Documentation & CodeGen</span>
            <a
              href="https://www.apimatic.io/"
              target="_blank"
              rel="noreferrer"
              className="font-bold underline text-blue-700"
            >
              apimatic.io ↗
            </a>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 bg-slate-50 border-t border-slate-200 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 rounded-xl bg-gray-900 text-white text-xs font-bold hover:bg-gray-800 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
