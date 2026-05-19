# Infra - Infraestrutura como Codigo

Modulos Terraform para provisionamento dos recursos AWS do SAIRA.

## Modulos

| Modulo | Recurso | Descricao |
| ------ | ------- | --------- |
| `s3` | S3 Bucket | Armazenamento de imagens de deteccoes |
| `sqs` | SQS Queue | Fila de mensagens entre cameras e YOLO worker |
| `rds` | RDS PostgreSQL | Banco de dados gerenciado com PostGIS |
| `ecs` | ECS Fargate | Hospedagem do backend e frontend |
| `iam` | IAM Roles | Permissoes para servicos (ECS, EC2, S3, SQS) |
| `ec2_yolo_vm` | EC2 Instance | VM dedicada para o worker YOLO |

## Ambientes

```text
infra/terraform/envs/
├── dev/dev.dev         # Variaveis do ambiente de desenvolvimento
└── prod/prod.prod      # Variaveis do ambiente de producao
```

## Uso

```bash
cd infra/terraform/envs/dev
terraform init
terraform plan
terraform apply
```
