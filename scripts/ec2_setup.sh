#!/bin/bash
# EC2 一键部署脚本 - Amazon Linux 2023

set -e

echo "=== 1. 安装 Docker ==="
sudo yum update -y
sudo yum install -y docker git
sudo service docker start
sudo systemctl enable docker
sudo usermod -a -G docker ec2-user

echo "=== 2. 安装 Docker Compose ==="
# 安装 Docker Compose 插件
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# 同时创建传统命令的软链接
sudo ln -sf /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose

echo "=== 3. 验证安装 ==="
docker --version
docker-compose --version

echo "=== 4. 创建环境变量文件 ==="
if [ ! -f .env ]; then
    cp env.example .env
    echo "已创建 .env 文件，请根据需要修改配置"
fi

echo "=== 5. 启动服务 ==="
# 需要用 newgrp 或重新登录才能使用 docker 组权限
# 这里用 sudo 来启动
sudo docker-compose up -d

echo "=== 6. 等待服务启动 ==="
sleep 10

echo "=== 7. 检查服务状态 ==="
sudo docker-compose ps

echo "=== 8. 测试 API ==="
curl -s http://localhost:8000/health | head -20

echo ""
echo "=== 部署完成 ==="
echo "API 地址: http://localhost:8000"
echo "Admin Portal: http://localhost:8005"
echo "DynamoDB Admin: http://localhost:8002"
echo ""
echo "查看日志: sudo docker-compose logs -f api"
echo "停止服务: sudo docker-compose down"
