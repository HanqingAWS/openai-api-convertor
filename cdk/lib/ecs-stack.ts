import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import { Construct } from 'constructs';
import { EnvironmentConfig } from '../config/config';
import * as path from 'path';

export interface ECSStackProps extends cdk.StackProps {
  config: EnvironmentConfig;
  vpc: ec2.Vpc;
  albSecurityGroup: ec2.SecurityGroup;
  ecsSecurityGroup: ec2.SecurityGroup;
  apiKeysTable: dynamodb.Table;
  usageTable: dynamodb.Table;
  modelMappingTable: dynamodb.Table;
  pricingTable: dynamodb.Table;
  usageStatsTable: dynamodb.Table;
  // Cognito (optional - for admin portal)
  cognitoUserPoolId?: string;
  cognitoClientId?: string;
}

export class ECSStack extends cdk.Stack {
  public readonly cluster: ecs.Cluster;
  public readonly service: ecs.FargateService;
  public readonly alb: elbv2.ApplicationLoadBalancer;

  constructor(scope: Construct, id: string, props: ECSStackProps) {
    super(scope, id, props);

    const { config, vpc, albSecurityGroup, ecsSecurityGroup } = props;
    const { apiKeysTable, usageTable, modelMappingTable } = props;
    const { pricingTable, usageStatsTable } = props;
    const { cognitoUserPoolId, cognitoClientId } = props;

    // ECS Cluster
    this.cluster = new ecs.Cluster(this, 'Cluster', {
      clusterName: `openai-proxy-${config.environmentName}`,
      vpc,
    });

    // ALB
    this.alb = new elbv2.ApplicationLoadBalancer(this, 'ALB', {
      loadBalancerName: `openai-proxy-${config.environmentName}-alb`,
      vpc,
      internetFacing: true,
      securityGroup: albSecurityGroup,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
    });

    // Target Group
    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'TargetGroup', {
      targetGroupName: `openai-proxy-${config.environmentName}-tg`,
      vpc,
      port: config.containerPort,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        path: config.healthCheckPath,
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // Listener
    this.alb.addListener('HTTPListener', {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
      defaultTargetGroups: [targetGroup],
    });

    // Log Group
    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: `/ecs/openai-proxy-${config.environmentName}`,
      retention: config.logRetentionDays as logs.RetentionDays,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Task Execution Role
    const taskExecutionRole = new iam.Role(this, 'TaskExecutionRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AmazonECSTaskExecutionRolePolicy'),
      ],
    });

    // Task Role
    const taskRole = new iam.Role(this, 'TaskRole', {
      assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
    });

    // Grant DynamoDB permissions
    apiKeysTable.grantReadWriteData(taskRole);
    usageTable.grantReadWriteData(taskRole);
    modelMappingTable.grantReadWriteData(taskRole);
    pricingTable.grantReadWriteData(taskRole);
    usageStatsTable.grantReadWriteData(taskRole);

    // Grant Bedrock permissions
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: ['*'],
      })
    );

    // Grant AWS Marketplace permissions (required for marketplace-based models like Claude Opus 4.6)
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'aws-marketplace:ViewSubscriptions',
          'aws-marketplace:Subscribe',
        ],
        resources: ['*'],
      })
    );
    
    // Master API Key Secret
    const masterApiKeySecret = new secretsmanager.Secret(this, 'MasterAPIKeySecret', {
      secretName: `openai-proxy-${config.environmentName}-master-api-key`,
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ username: 'master' }),
        generateStringKey: 'password',
        excludePunctuation: true,
        passwordLength: 32,
      },
    });

    masterApiKeySecret.grantRead(taskRole);

    // Platform
    const cpuArchitecture = config.platform === 'arm64'
      ? ecs.CpuArchitecture.ARM64
      : ecs.CpuArchitecture.X86_64;

    const dockerPlatform = config.platform === 'arm64'
      ? Platform.LINUX_ARM64
      : Platform.LINUX_AMD64;

    // Task Definition
    const taskDefinition = new ecs.FargateTaskDefinition(this, 'TaskDefinition', {
      family: `openai-proxy-${config.environmentName}`,
      cpu: config.ecsCpu,
      memoryLimitMiB: config.ecsMemory,
      executionRole: taskExecutionRole,
      taskRole: taskRole,
      runtimePlatform: {
        cpuArchitecture,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    // Container
    taskDefinition.addContainer('app', {
      containerName: 'openai-proxy',
      image: ecs.ContainerImage.fromAsset(path.join(__dirname, '../../'), {
        file: 'Dockerfile',
        exclude: ['cdk/cdk.out', 'cdk/node_modules', '.git'],
        platform: dockerPlatform,
      }),
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: 'openai-proxy',
        logGroup,
      }),
      environment: {
        AWS_REGION: config.region,
        ENVIRONMENT: config.environmentName,
        DYNAMODB_API_KEYS_TABLE: apiKeysTable.tableName,
        DYNAMODB_USAGE_TABLE: usageTable.tableName,
        DYNAMODB_MODEL_MAPPING_TABLE: modelMappingTable.tableName,
        DYNAMODB_PRICING_TABLE: pricingTable.tableName,
        DYNAMODB_USAGE_STATS_TABLE: usageStatsTable.tableName,
        REQUIRE_API_KEY: config.requireApiKey.toString(),
        RATE_LIMIT_ENABLED: config.rateLimitEnabled.toString(),
        RATE_LIMIT_REQUESTS: config.rateLimitRequests.toString(),
        RATE_LIMIT_WINDOW: config.rateLimitWindow.toString(),
        ENABLE_PROMPT_CACHING: 'true',
        PROMPT_CACHE_MIN_TOKENS: '1024',
        DEFAULT_CACHE_TTL: '5m',
      },
      secrets: {
        MASTER_API_KEY: ecs.Secret.fromSecretsManager(masterApiKeySecret, 'password'),
      },
      portMappings: [
        { containerPort: config.containerPort, protocol: ecs.Protocol.TCP },
      ],
      healthCheck: {
        command: ['CMD-SHELL', `curl -f http://localhost:${config.containerPort}/health || exit 1`],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    // Fargate Service
    this.service = new ecs.FargateService(this, 'Service', {
      serviceName: `openai-proxy-${config.environmentName}`,
      cluster: this.cluster,
      taskDefinition,
      desiredCount: config.ecsDesiredCount,
      assignPublicIp: false,
      securityGroups: [ecsSecurityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      healthCheckGracePeriod: cdk.Duration.seconds(120),
      circuitBreaker: { rollback: true },
    });

    this.service.attachToApplicationTargetGroup(targetGroup);

    // Auto Scaling
    const scaling = this.service.autoScaleTaskCount({
      minCapacity: config.ecsMinCapacity,
      maxCapacity: config.ecsMaxCapacity,
    });

    scaling.scaleOnCpuUtilization('CpuScaling', {
      targetUtilizationPercent: config.ecsTargetCpuUtilization,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });

    // Admin Portal Service
    if (config.adminPortalEnabled) {
      this.createAdminPortalService(
        config, vpc, ecsSecurityGroup, taskExecutionRole, taskRole,
        cpuArchitecture, dockerPlatform, apiKeysTable, usageTable, modelMappingTable,
        pricingTable, usageStatsTable, cognitoUserPoolId, cognitoClientId
      );
    }

    // Tags
    Object.entries(config.tags).forEach(([key, value]) => {
      cdk.Tags.of(this).add(key, value);
    });

    // Outputs
    new cdk.CfnOutput(this, 'ClusterName', {
      value: this.cluster.clusterName,
    });

    new cdk.CfnOutput(this, 'ServiceName', {
      value: this.service.serviceName,
    });

    new cdk.CfnOutput(this, 'ALBDNSName', {
      value: this.alb.loadBalancerDnsName,
      description: 'API Endpoint',
    });

    new cdk.CfnOutput(this, 'MasterAPIKeySecretName', {
      value: masterApiKeySecret.secretName,
    });
  }

  /**
   * Create Admin Portal Fargate service
   */
  private createAdminPortalService(
    config: EnvironmentConfig,
    vpc: ec2.Vpc,
    ecsSecurityGroup: ec2.SecurityGroup,
    taskExecutionRole: iam.Role,
    taskRole: iam.Role,
    cpuArchitecture: ecs.CpuArchitecture,
    dockerPlatform: Platform,
    apiKeysTable: dynamodb.Table,
    usageTable: dynamodb.Table,
    modelMappingTable: dynamodb.Table,
    pricingTable: dynamodb.Table,
    usageStatsTable: dynamodb.Table,
    cognitoUserPoolId?: string,
    cognitoClientId?: string,
  ): void {
    // Admin Portal Log Group
    const adminLogGroup = new logs.LogGroup(this, 'AdminPortalLogGroup', {
      logGroupName: `/ecs/openai-proxy-admin-${config.environmentName}`,
      retention: config.logRetentionDays as logs.RetentionDays,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Admin Portal Task Definition
    const adminTaskDefinition = new ecs.FargateTaskDefinition(this, 'AdminPortalTaskDefinition', {
      family: `openai-proxy-admin-${config.environmentName}`,
      cpu: config.adminPortalCpu,
      memoryLimitMiB: config.adminPortalMemory,
      executionRole: taskExecutionRole,
      taskRole: taskRole,
      runtimePlatform: {
        cpuArchitecture,
        operatingSystemFamily: ecs.OperatingSystemFamily.LINUX,
      },
    });

    // Admin Portal Container
    adminTaskDefinition.addContainer('admin-portal', {
      containerName: 'admin-portal',
      image: ecs.ContainerImage.fromAsset(path.join(__dirname, '../../'), {
        file: 'admin_portal/Dockerfile',
        exclude: ['cdk/cdk.out', 'cdk/node_modules', '.git'],
        platform: dockerPlatform,
      }),
      logging: ecs.LogDriver.awsLogs({
        streamPrefix: 'admin-portal',
        logGroup: adminLogGroup,
      }),
      environment: {
        AWS_REGION: config.region,
        ENVIRONMENT: config.environmentName,
        DYNAMODB_API_KEYS_TABLE: apiKeysTable.tableName,
        DYNAMODB_USAGE_TABLE: usageTable.tableName,
        DYNAMODB_MODEL_MAPPING_TABLE: modelMappingTable.tableName,
        DYNAMODB_PRICING_TABLE: pricingTable.tableName,
        DYNAMODB_USAGE_STATS_TABLE: usageStatsTable.tableName,
        // Cognito (if configured)
        ...(cognitoUserPoolId && { COGNITO_USER_POOL_ID: cognitoUserPoolId }),
        ...(cognitoClientId && { COGNITO_CLIENT_ID: cognitoClientId }),
        COGNITO_REGION: config.region,
        // Static file serving
        SERVE_STATIC_FILES: 'true',
      },
      portMappings: [
        { containerPort: config.adminPortalContainerPort, protocol: ecs.Protocol.TCP },
      ],
      healthCheck: {
        command: ['CMD-SHELL', `curl -f http://localhost:${config.adminPortalContainerPort}/health || exit 1`],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    // Admin Portal Target Group
    const adminTargetGroup = new elbv2.ApplicationTargetGroup(this, 'AdminPortalTargetGroup', {
      targetGroupName: `openai-proxy-admin-${config.environmentName}-tg`,
      vpc,
      port: config.adminPortalContainerPort,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        path: '/health',
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 5,
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // Add path-based routing for /admin/* and /api/*
    const listener = this.alb.listeners[0];
    listener.addTargetGroups('AdminPortalRouting', {
      priority: 10,
      conditions: [
        elbv2.ListenerCondition.pathPatterns(['/admin', '/admin/*', '/api/*']),
      ],
      targetGroups: [adminTargetGroup],
    });

    // Admin Portal Fargate Service
    const adminService = new ecs.FargateService(this, 'AdminPortalService', {
      serviceName: `openai-proxy-admin-${config.environmentName}`,
      cluster: this.cluster,
      taskDefinition: adminTaskDefinition,
      desiredCount: 1,
      assignPublicIp: false,
      securityGroups: [ecsSecurityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      healthCheckGracePeriod: cdk.Duration.seconds(120),
      circuitBreaker: { rollback: true },
    });

    adminService.attachToApplicationTargetGroup(adminTargetGroup);

    // Output
    new cdk.CfnOutput(this, 'AdminPortalURL', {
      value: `http://${this.alb.loadBalancerDnsName}/admin/`,
      description: 'Admin Portal URL',
    });
  }
}
