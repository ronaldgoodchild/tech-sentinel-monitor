# Tech Sentinel Monitor — Secrets & Vault Guide

## Required Secrets

| Secret | Purpose | Where Used |
|--------|---------|------------|
| `TS_JWT_SECRET` | JWT token signing | Control Plane API |
| `POSTGRES_PASSWORD` | Database auth | All services |
| `TS_API_KEY` | Global admin API key | Control Plane API |
| `TS_SLACK_WEBHOOK_URL` | Default Slack notifications | Alert Engine |
| `TS_PAGERDUTY_ROUTING_KEY` | Default PagerDuty routing | Alert Engine |
| `TS_AUTOMATION_URL` | Tech Sentinel remediation endpoint | Alert Engine |
| `TS_AUTOMATION_API_KEY` | Auth for remediation endpoint | Alert Engine |

## Local Development

Use `.env` file (never commit to git):

```bash
cp .env.example .env
# Edit with your values
```

## HashiCorp Vault Integration (KV v2)

### Store secrets
```bash
vault kv put secret/tech-sentinel \
  jwt_secret="$(openssl rand -hex 32)" \
  postgres_password="$(openssl rand -hex 16)" \
  api_key="$(uuidgen)"
```

### Read secrets
```bash
vault kv get -field=jwt_secret secret/tech-sentinel
```

### AppRole Auth (for services)
```bash
# Enable AppRole
vault auth enable approle

# Create policy
vault policy write ts-policy - <<EOF
path "secret/data/tech-sentinel" {
  capabilities = ["read"]
}
EOF

# Create role
vault write auth/approle/role/tech-sentinel \
  token_policies="ts-policy" \
  token_ttl=1h \
  token_max_ttl=4h
```

## Kubernetes Secrets

### Create secret
```bash
kubectl create secret generic ts-secrets \
  --from-literal=jwt-secret="$(openssl rand -hex 32)" \
  --from-literal=postgres-password="$(openssl rand -hex 16)" \
  --from-literal=api-key="$(uuidgen)"
```

### External Secrets Operator
```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ts-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: ts-secrets
  data:
    - secretKey: jwt-secret
      remoteRef:
        key: secret/tech-sentinel
        property: jwt_secret
    - secretKey: postgres-password
      remoteRef:
        key: secret/tech-sentinel
        property: postgres_password
```

## Secret Rotation

### JWT Secret
1. Generate new secret: `openssl rand -hex 32`
2. Update in Vault/K8s/`.env`
3. Rolling restart of Control Plane: `docker compose restart control-plane`
4. Existing tokens will be invalidated (short-lived, max 60min)

### Database Password
1. Update password in PostgreSQL
2. Update in Vault/K8s/`.env`
3. Rolling restart of all services

### API Keys
1. Create new tenant API key via API
2. Update client configurations
3. Old key remains valid until tenant is deleted
