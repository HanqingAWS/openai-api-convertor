import { useState } from 'react';
import {
  useProviders,
  useCreateProvider,
  useUpdateProvider,
  useDeleteProvider,
} from '../hooks/useProviders';
import type { Provider, ProviderCreate, ProviderUpdate } from '../types';

function SlideOver({
  isOpen,
  onClose,
  title,
  children,
}: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose}></div>
      <div className="absolute inset-y-0 right-0 max-w-md w-full bg-surface-dark shadow-2xl border-l border-border-dark flex flex-col">
        <div className="px-6 py-4 border-b border-border-dark flex items-center justify-between">
          <h2 className="text-lg font-bold text-white">{title}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-300">
            <span className="material-symbols-outlined">close</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
      </div>
    </div>
  );
}

function ProviderForm({
  initial,
  onSubmit,
  isLoading,
}: {
  initial?: Provider;
  onSubmit: (data: ProviderCreate | ProviderUpdate) => void;
  isLoading: boolean;
}) {
  const [name, setName] = useState(initial?.name || '');
  const [awsRegion, setAwsRegion] = useState(initial?.aws_region || 'us-east-1');
  const [authType, setAuthType] = useState<'ak_sk' | 'bearer_token'>(initial?.auth_type || 'bearer_token');
  const [accessKeyId, setAccessKeyId] = useState('');
  const [secretAccessKey, setSecretAccessKey] = useState('');
  const [bearerToken, setBearerToken] = useState('');
  const [endpointUrl, setEndpointUrl] = useState(initial?.endpoint_url || '');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const data: any = { name, aws_region: awsRegion, auth_type: authType };
    if (authType === 'ak_sk') {
      if (accessKeyId) data.access_key_id = accessKeyId;
      if (secretAccessKey) data.secret_access_key = secretAccessKey;
    } else {
      if (bearerToken) data.bearer_token = bearerToken;
    }
    if (endpointUrl) data.endpoint_url = endpointUrl;
    onSubmit(data);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">Name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          className="w-full px-3 py-2 bg-background-dark border border-border-dark rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary"
          placeholder="e.g. Production Account"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">AWS Region</label>
        <input
          type="text"
          value={awsRegion}
          onChange={(e) => setAwsRegion(e.target.value)}
          required
          className="w-full px-3 py-2 bg-background-dark border border-border-dark rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary"
          placeholder="us-east-1"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">Auth Type</label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="radio"
              name="authType"
              value="ak_sk"
              checked={authType === 'ak_sk'}
              onChange={() => setAuthType('ak_sk')}
              className="text-primary"
            />
            AK/SK
          </label>
          <label className="flex items-center gap-2 text-slate-300">
            <input
              type="radio"
              name="authType"
              value="bearer_token"
              checked={authType === 'bearer_token'}
              onChange={() => setAuthType('bearer_token')}
              className="text-primary"
            />
            Bearer Token
          </label>
        </div>
      </div>

      {authType === 'ak_sk' && (
        <>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Access Key ID {initial && <span className="text-slate-500">(leave blank to keep current)</span>}
            </label>
            <input
              type="text"
              value={accessKeyId}
              onChange={(e) => setAccessKeyId(e.target.value)}
              required={!initial}
              className="w-full px-3 py-2 bg-background-dark border border-border-dark rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
              placeholder="AKIA..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">
              Secret Access Key {initial && <span className="text-slate-500">(leave blank to keep current)</span>}
            </label>
            <input
              type="password"
              value={secretAccessKey}
              onChange={(e) => setSecretAccessKey(e.target.value)}
              required={!initial}
              className="w-full px-3 py-2 bg-background-dark border border-border-dark rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
              placeholder="wJalr..."
            />
          </div>
        </>
      )}

      {authType === 'bearer_token' && (
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">
            Bearer Token {initial && <span className="text-slate-500">(leave blank to keep current)</span>}
          </label>
          <textarea
            value={bearerToken}
            onChange={(e) => setBearerToken(e.target.value)}
            required={!initial}
            rows={3}
            className="w-full px-3 py-2 bg-background-dark border border-border-dark rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary font-mono text-sm"
            placeholder="eyJ..."
          />
        </div>
      )}

      <div>
        <label className="block text-sm font-medium text-slate-300 mb-1">
          Endpoint URL <span className="text-slate-500">(optional)</span>
        </label>
        <input
          type="text"
          value={endpointUrl}
          onChange={(e) => setEndpointUrl(e.target.value)}
          className="w-full px-3 py-2 bg-background-dark border border-border-dark rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-primary text-sm"
          placeholder="https://custom-endpoint.example.com"
        />
      </div>

      <button
        type="submit"
        disabled={isLoading}
        className="w-full py-2.5 bg-primary hover:bg-primary/90 text-white font-medium rounded-lg transition-colors disabled:opacity-50"
      >
        {isLoading ? 'Saving...' : initial ? 'Update Provider' : 'Create Provider'}
      </button>
    </form>
  );
}

export default function ProvidersPage() {
  const [showCreatePanel, setShowCreatePanel] = useState(false);
  const [editingProvider, setEditingProvider] = useState<Provider | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  const { data, isLoading, error } = useProviders();
  const createMutation = useCreateProvider();
  const updateMutation = useUpdateProvider();
  const deleteMutation = useDeleteProvider();

  const handleCreate = async (formData: ProviderCreate | ProviderUpdate) => {
    try {
      await createMutation.mutateAsync(formData as ProviderCreate);
      setShowCreatePanel(false);
    } catch (err) {
      console.error('Failed to create provider:', err);
    }
  };

  const handleUpdate = async (formData: ProviderCreate | ProviderUpdate) => {
    if (!editingProvider) return;
    try {
      await updateMutation.mutateAsync({
        providerId: editingProvider.provider_id,
        data: formData as ProviderUpdate,
      });
      setEditingProvider(null);
    } catch (err) {
      console.error('Failed to update provider:', err);
    }
  };

  const handleDelete = async (providerId: string) => {
    try {
      await deleteMutation.mutateAsync(providerId);
      setDeleteConfirm(null);
    } catch (err) {
      console.error('Failed to delete provider:', err);
    }
  };

  const handleToggleActive = async (provider: Provider) => {
    try {
      await updateMutation.mutateAsync({
        providerId: provider.provider_id,
        data: { is_active: !provider.is_active },
      });
    } catch (err) {
      console.error('Failed to toggle provider:', err);
    }
  };

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-red-400">
          Failed to load providers: {(error as Error).message}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Providers</h1>
          <p className="text-sm text-slate-400 mt-1">
            Configure AWS credential providers for Bedrock access
          </p>
        </div>
        <button
          onClick={() => setShowCreatePanel(true)}
          className="flex items-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary/90 text-white font-medium rounded-lg transition-colors"
        >
          <span className="material-symbols-outlined text-[18px]">add</span>
          Add Provider
        </button>
      </div>

      {/* Table */}
      <div className="bg-surface-dark border border-border-dark rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border-dark">
              <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Name</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Region</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Auth Type</th>
              <th className="text-left px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Status</th>
              <th className="text-right px-6 py-3 text-xs font-semibold text-slate-400 uppercase tracking-wider">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-dark">
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-slate-400">Loading...</td>
              </tr>
            ) : !data?.items?.length ? (
              <tr>
                <td colSpan={5} className="px-6 py-8 text-center text-slate-400">
                  No providers configured. Click "Add Provider" to create one.
                </td>
              </tr>
            ) : (
              data.items.map((provider) => (
                <tr key={provider.provider_id} className="hover:bg-white/[0.02]">
                  <td className="px-6 py-4">
                    <span className="text-white font-medium">{provider.name}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-slate-300 font-mono text-sm">{provider.aws_region}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                      provider.auth_type === 'ak_sk'
                        ? 'bg-blue-500/10 text-blue-400'
                        : 'bg-purple-500/10 text-purple-400'
                    }`}>
                      {provider.auth_type === 'ak_sk' ? 'AK/SK' : 'Bearer Token'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <button
                      onClick={() => handleToggleActive(provider)}
                      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium cursor-pointer ${
                        provider.is_active
                          ? 'bg-green-500/10 text-green-400'
                          : 'bg-red-500/10 text-red-400'
                      }`}
                    >
                      {provider.is_active ? 'Active' : 'Inactive'}
                    </button>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => setEditingProvider(provider)}
                        className="p-1.5 text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="Edit"
                      >
                        <span className="material-symbols-outlined text-[18px]">edit</span>
                      </button>
                      <button
                        onClick={() => setDeleteConfirm(provider.provider_id)}
                        className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
                        title="Delete"
                      >
                        <span className="material-symbols-outlined text-[18px]">delete</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Create Panel */}
      <SlideOver
        isOpen={showCreatePanel}
        onClose={() => setShowCreatePanel(false)}
        title="Add Provider"
      >
        <ProviderForm onSubmit={handleCreate} isLoading={createMutation.isPending} />
      </SlideOver>

      {/* Edit Panel */}
      <SlideOver
        isOpen={!!editingProvider}
        onClose={() => setEditingProvider(null)}
        title="Edit Provider"
      >
        {editingProvider && (
          <ProviderForm
            initial={editingProvider}
            onSubmit={handleUpdate}
            isLoading={updateMutation.isPending}
          />
        )}
      </SlideOver>

      {/* Delete Confirmation */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={() => setDeleteConfirm(null)}></div>
          <div className="relative bg-surface-dark border border-border-dark rounded-xl p-6 max-w-sm w-full mx-4">
            <h3 className="text-lg font-bold text-white mb-2">Delete Provider</h3>
            <p className="text-slate-400 mb-4">
              Are you sure? API keys bound to this provider will fall back to IAM Role authentication.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="px-4 py-2 text-slate-300 hover:text-white border border-border-dark rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
