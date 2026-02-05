/**
 * Configuration for different deployment environments
 */

export interface EnvironmentConfig {
  account?: string;
  region: string;
  environmentName: string;
  platform: 'arm64' | 'amd64';

  // VPC
  vpcCidr: string;
  maxAzs: number;

  // ECS
  ecsDesiredCount: number;
  ecsCpu: number;
  ecsMemory: number;
  ecsMinCapacity: number;
  ecsMaxCapacity: number;
  ecsTargetCpuUtilization: number;

  // Container
  containerPort: number;
  healthCheckPath: string;

  // Application
  requireApiKey: boolean;
  rateLimitEnabled: boolean;
  rateLimitRequests: number;
  rateLimitWindow: number;

  // Logging
  logRetentionDays: number;

  // Admin Portal
  adminPortalEnabled: boolean;
  adminPortalCpu: number;
  adminPortalMemory: number;
  adminPortalContainerPort: number;

  // Tags
  tags: { [key: string]: string };
}

type EnvironmentConfigWithoutPlatform = Omit<EnvironmentConfig, 'platform'>;

export const environments: { [key: string]: EnvironmentConfigWithoutPlatform } = {
  dev: {
    region: process.env.AWS_REGION || 'us-west-2',
    environmentName: 'dev',

    vpcCidr: '10.0.0.0/16',
    maxAzs: 2,

    ecsDesiredCount: 1,
    ecsCpu: 512,
    ecsMemory: 1024,
    ecsMinCapacity: 1,
    ecsMaxCapacity: 2,
    ecsTargetCpuUtilization: 70,

    containerPort: 8000,
    healthCheckPath: '/health',

    requireApiKey: true,
    rateLimitEnabled: true,
    rateLimitRequests: 100,
    rateLimitWindow: 60,

    logRetentionDays: 7,

    // Admin Portal
    adminPortalEnabled: true,
    adminPortalCpu: 512,
    adminPortalMemory: 1024,
    adminPortalContainerPort: 8005,

    tags: {
      Environment: 'dev',
      Project: 'openai-api-convertor',
      ManagedBy: 'CDK',
    },
  },

  prod: {
    region: process.env.AWS_REGION || 'us-west-2',
    environmentName: 'prod',

    vpcCidr: '10.1.0.0/16',
    maxAzs: 3,

    ecsDesiredCount: 2,
    ecsCpu: 1024,
    ecsMemory: 2048,
    ecsMinCapacity: 2,
    ecsMaxCapacity: 10,
    ecsTargetCpuUtilization: 70,

    containerPort: 8000,
    healthCheckPath: '/health',

    requireApiKey: true,
    rateLimitEnabled: true,
    rateLimitRequests: 1000,
    rateLimitWindow: 60,

    logRetentionDays: 30,

    // Admin Portal
    adminPortalEnabled: true,
    adminPortalCpu: 512,
    adminPortalMemory: 1024,
    adminPortalContainerPort: 8005,

    tags: {
      Environment: 'prod',
      Project: 'openai-api-convertor',
      ManagedBy: 'CDK',
    },
  },
};

export function getConfig(environmentName: string = 'dev'): EnvironmentConfig {
  const config = environments[environmentName];
  if (!config) {
    throw new Error(
      `Unknown environment: ${environmentName}. Available: ${Object.keys(environments).join(', ')}`
    );
  }

  const platform = process.env.CDK_PLATFORM as 'arm64' | 'amd64';
  if (!platform || !['arm64', 'amd64'].includes(platform)) {
    throw new Error(
      `Platform must be specified via CDK_PLATFORM. Valid values: arm64, amd64. Got: ${platform}`
    );
  }

  return { ...config, platform };
}
