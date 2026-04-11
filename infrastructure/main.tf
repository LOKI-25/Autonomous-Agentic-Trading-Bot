terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# --- 1. SECURITY GROUP (Firewall) ---
resource "aws_security_group" "trading_bot_sg" {
  name        = "trading-bot-security-group"
  description = "Allow inbound traffic for FastAPI and SSH"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- 2. BACKEND: EC2 INSTANCE ---
data "aws_ami" "ubuntu" {
  most_recent = true
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  owners = ["802437129860"] # Canonical's AWS Account ID
}

resource "aws_instance" "backend_server" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = "t3.micro"
  vpc_security_group_ids = [aws_security_group.trading_bot_sg.id]

  user_data = <<-EOF
              #!/bin/bash
              apt-get update -y
              apt-get install -y python3-pip python3-venv git
              # In a real deployment, you would clone your GitHub repo here:
              # git clone https://github.com/YourUsername/Autonomous-Trading-bot.git /app
              # cd /app && pip install -r requirements.txt
              # uvicorn servers.risk_gatekeeper.admin_dashboard:app --host 0.0.0.0 --port 8000 &
              EOF

  tags = {
    Name = "TradingBot-Backend"
  }
}

# --- 3. FRONTEND: S3 STATIC WEBSITE ---
resource "aws_s3_bucket" "frontend_bucket" {
  bucket = "trading-bot-frontend-dashboard-12345" # MUST be globally unique across all of AWS!
}

resource "aws_s3_bucket_public_access_block" "frontend_public_access" {
  bucket = aws_s3_bucket.frontend_bucket.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "frontend_website" {
  bucket = aws_s3_bucket.frontend_bucket.id
  index_document { suffix = "index.html" }
  error_document { key = "index.html" }
}

# --- 4. OUTPUTS ---
output "backend_api_url" {
  value = "http://${aws_instance.backend_server.public_ip}:8000"
}
output "frontend_website_url" {
  value = aws_s3_bucket_website_configuration.frontend_website.website_endpoint
}