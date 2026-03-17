#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { NetworkStack } from '../lib/network-stack';
import { DynamoDBStack } from '../lib/dynamodb-stack';
import { CognitoStack } from '../lib/cognito-stack';
import { ECSStack } from '../lib/ecs-stack';
import { getConfig } from '../config/config';

const app = new cdk.App();

const environmentName = app.node.tryGetContext('environment') || 'dev';
const config = getConfig(environmentName);

const env = {
  account: config.account || process.env.CDK_DEFAULT_ACCOUNT,
  region: config.region,
};

// Network Stack
const networkStack = new NetworkStack(app, `OpenAIProxy-Network-${config.environmentName}`, {
  env,
  config,
});

// DynamoDB Stack
const dynamodbStack = new DynamoDBStack(app, `OpenAIProxy-DynamoDB-${config.environmentName}`, {
  env,
  config,
});

// Cognito Stack (for admin portal authentication)
const cognitoStack = config.adminPortalEnabled
  ? new CognitoStack(app, `OpenAIProxy-Cognito-${config.environmentName}`, {
      env,
      config,
    })
  : undefined;

// ECS Stack
const ecsStack = new ECSStack(app, `OpenAIProxy-ECS-${config.environmentName}`, {
  env,
  config,
  vpc: networkStack.vpc,
  albSecurityGroup: networkStack.albSecurityGroup,
  ecsSecurityGroup: networkStack.ecsSecurityGroup,
  apiKeysTable: dynamodbStack.apiKeysTable,
  usageTable: dynamodbStack.usageTable,
  modelMappingTable: dynamodbStack.modelMappingTable,
  pricingTable: dynamodbStack.pricingTable,
  usageStatsTable: dynamodbStack.usageStatsTable,
  cognitoUserPoolId: cognitoStack?.userPool.userPoolId,
  cognitoClientId: cognitoStack?.userPoolClient.userPoolClientId,
});

if (cognitoStack) {
  ecsStack.addDependency(cognitoStack);
}
