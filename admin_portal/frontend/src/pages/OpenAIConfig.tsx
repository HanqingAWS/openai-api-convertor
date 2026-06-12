import { useState, useEffect } from 'react';
import { useOpenAIConfig, useUpdateOpenAIConfig } from '../hooks/useOpenAIConfig';

export default function OpenAIConfigPage() {
  const { data: config, isLoading, error } = useOpenAIConfig();
  const updateMutation = useUpdateOpenAIConfig();

  const [baseUrl, setBaseUrl] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (config) {
      setBaseUrl(config.base_url || '');
    }
  }, [config]);

  const handleSave = async () => {
    await updateMutation.mutateAsync({ base_url: baseUrl });
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent-blue"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
          Failed to load OpenAI configuration
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">OpenAI Configuration</h1>
        <p className="text-slate-400 mt-1">
          Configure Bedrock Mantle endpoint for OpenAI model access.
          Authentication is managed via Providers.
        </p>
      </div>

      <div className="space-y-6 bg-surface-dark rounded-xl border border-border-dark p-6">
        {/* Base URL */}
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-2">
            Base URL
          </label>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://bedrock-mantle.us-east-2.api.aws/openai/v1"
            className="w-full px-4 py-2.5 bg-slate-800 border border-border-dark rounded-lg text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-accent-blue/50 focus:border-accent-blue"
          />
          <p className="text-xs text-slate-500 mt-1">
            Bedrock Mantle OpenAI-compatible endpoint
          </p>
        </div>

        {/* Save Button */}
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleSave}
            disabled={updateMutation.isPending}
            className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg font-medium transition-colors"
          >
            {updateMutation.isPending ? 'Saving...' : 'Save Configuration'}
          </button>
          {saved && (
            <span className="text-green-400 text-sm flex items-center gap-1">
              <span className="material-symbols-outlined text-sm">check_circle</span>
              Saved successfully
            </span>
          )}
        </div>

        {/* Last Updated */}
        {config?.updated_at && (
          <p className="text-xs text-slate-500">
            Last updated: {new Date(config.updated_at).toLocaleString()}
          </p>
        )}
      </div>
    </div>
  );
}
