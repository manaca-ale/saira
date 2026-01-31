# Nginx - API Gateway

Reverse proxy que roteia requisicoes externas para o backend FastAPI.

## Configuracao

Arquivo: `gateway.conf`

### Rotas

| Path | Destino | Descricao |
| ---- | ------- | --------- |
| `/api/*` | `backend:8001` | Todas as chamadas de API |
| `/health` | `backend:8001/health` | Health check |

### Headers propagados

- `X-Real-IP`
- `X-Forwarded-For`
- `X-Forwarded-Proto`
- `Authorization`

## Uso

O gateway e utilizado nos ambientes de teste e producao via Docker Compose:

```yaml
# docker-compose.prod.yml
api-gateway:
  image: nginx:alpine
  ports:
    - "5000:80"
  volumes:
    - ./nginx/gateway.conf:/etc/nginx/conf.d/default.conf
```

No ambiente de desenvolvimento, o frontend se comunica diretamente com o backend na porta 8001.
