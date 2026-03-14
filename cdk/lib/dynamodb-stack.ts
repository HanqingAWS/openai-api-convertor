import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';
import { EnvironmentConfig } from '../config/config';

export interface DynamoDBStackProps extends cdk.StackProps {
  config: EnvironmentConfig;
}

export class DynamoDBStack extends cdk.Stack {
  public readonly apiKeysTable: dynamodb.Table;
  public readonly usageTable: dynamodb.Table;
  public readonly modelMappingTable: dynamodb.Table;
  public readonly pricingTable: dynamodb.Table;
  public readonly usageStatsTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DynamoDBStackProps) {
    super(scope, id, props);

    const { config } = props;

    // API Keys Table
    this.apiKeysTable = new dynamodb.Table(this, 'APIKeysTable', {
      tableName: `openai-proxy-api-keys-${config.environmentName}`,
      partitionKey: { name: 'api_key', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.environmentName === 'prod'
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      pointInTimeRecoverySpecification: {
        pointInTimeRecoveryEnabled: config.environmentName === 'prod',
      },
    });

    this.apiKeysTable.addGlobalSecondaryIndex({
      indexName: 'user_id-index',
      partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
    });

    // Usage Table
    this.usageTable = new dynamodb.Table(this, 'UsageTable', {
      tableName: `openai-proxy-usage-${config.environmentName}`,
      partitionKey: { name: 'api_key', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'timestamp', type: dynamodb.AttributeType.NUMBER },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.environmentName === 'prod'
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
      timeToLiveAttribute: 'ttl',
    });

    this.usageTable.addGlobalSecondaryIndex({
      indexName: 'request_id-index',
      partitionKey: { name: 'request_id', type: dynamodb.AttributeType.STRING },
    });

    // Model Mapping Table
    this.modelMappingTable = new dynamodb.Table(this, 'ModelMappingTable', {
      tableName: `openai-proxy-model-mapping-${config.environmentName}`,
      partitionKey: { name: 'openai_model_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.environmentName === 'prod'
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    // Pricing Table
    this.pricingTable = new dynamodb.Table(this, 'PricingTable', {
      tableName: `openai-proxy-pricing-${config.environmentName}`,
      partitionKey: { name: 'model_id', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.environmentName === 'prod'
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    // Usage Stats Table (aggregated usage per API key)
    this.usageStatsTable = new dynamodb.Table(this, 'UsageStatsTable', {
      tableName: `openai-proxy-usage-stats-${config.environmentName}`,
      partitionKey: { name: 'api_key', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.environmentName === 'prod'
        ? cdk.RemovalPolicy.RETAIN
        : cdk.RemovalPolicy.DESTROY,
    });

    // Tags
    Object.entries(config.tags).forEach(([key, value]) => {
      cdk.Tags.of(this).add(key, value);
    });

    // Outputs
    new cdk.CfnOutput(this, 'APIKeysTableName', {
      value: this.apiKeysTable.tableName,
      description: 'API Keys Table Name',
    });

    new cdk.CfnOutput(this, 'UsageTableName', {
      value: this.usageTable.tableName,
      description: 'Usage Table Name',
    });

    new cdk.CfnOutput(this, 'ModelMappingTableName', {
      value: this.modelMappingTable.tableName,
      description: 'Model Mapping Table Name',
    });

    new cdk.CfnOutput(this, 'PricingTableName', {
      value: this.pricingTable.tableName,
      description: 'Pricing Table Name',
    });

    new cdk.CfnOutput(this, 'UsageStatsTableName', {
      value: this.usageStatsTable.tableName,
      description: 'Usage Stats Table Name',
    });
  }
}
