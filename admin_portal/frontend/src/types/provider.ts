export interface Provider {
  provider_id: string;
  name: string;
  aws_region: string;
  auth_type: 'ak_sk' | 'bearer_token';
  has_access_key: boolean;
  has_secret_access_key: boolean;
  has_bearer_token: boolean;
  endpoint_url?: string;
  is_active: boolean;
  created_at: number;
  updated_at: number;
}

export interface ProviderCreate {
  name: string;
  aws_region: string;
  auth_type: 'ak_sk' | 'bearer_token';
  access_key_id?: string;
  secret_access_key?: string;
  bearer_token?: string;
  endpoint_url?: string;
}

export interface ProviderUpdate {
  name?: string;
  aws_region?: string;
  auth_type?: 'ak_sk' | 'bearer_token';
  access_key_id?: string;
  secret_access_key?: string;
  bearer_token?: string;
  endpoint_url?: string;
  is_active?: boolean;
}

export interface ProviderListResponse {
  items: Provider[];
  count: number;
}
