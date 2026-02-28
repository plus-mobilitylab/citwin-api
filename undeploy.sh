#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-}"
if [[ -z "$ENVIRONMENT" ]]; then
  echo "Usage: ./undeploy.sh [environment]"
  echo "Example: ./undeploy.sh prod"
  exit 1
fi

ENV_FILE=".env.deploy.${ENVIRONMENT}"
[[ -f "$ENV_FILE" ]] || { echo "– environment file $ENV_FILE not found"; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

DEPLOY_USER="${DEPLOY_USER:-deploy}"

REQUIRED=(
  PROJECT_NAME
  SSH_USER SSH_HOST SSH_PORT
  DEPLOY_USER DEPLOY_PATH
  API_DOMAIN API_ROOT_PATH API_PORT
)

for VAR in "${REQUIRED[@]}"; do
  [[ -n "${!VAR:-}" ]] || { echo "– missing required variable: $VAR"; exit 1; }
done

echo "□ undeploying $PROJECT_NAME from $SSH_HOST using $ENV_FILE"

ssh_base=(ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST")

remote_deploy() {
  "${ssh_base[@]}" "sudo -u '$DEPLOY_USER' -H /bin/bash -lc '/bin/bash -se'" </dev/stdin
}

# ----------------------------------------------------------------------------------------------------------------------
# docker / project directory
# ----------------------------------------------------------------------------------------------------------------------

remote_deploy <<EOF
set -euo pipefail
if [[ -d "$DEPLOY_PATH" ]]; then
  echo "– stopping docker containers: $DEPLOY_PATH"
  cd "$DEPLOY_PATH"
  export PROJECT_NAME="$PROJECT_NAME"
  export API_PORT="$API_PORT"
  export API_ROOT_PATH="$API_ROOT_PATH"
  docker compose down --volumes || true
  echo "– removing project directory: $DEPLOY_PATH"
  rm -rf -- "$DEPLOY_PATH"
fi
EOF

# ----------------------------------------------------------------------------------------------------------------------
# nginx
# ----------------------------------------------------------------------------------------------------------------------

remote_deploy <<EOF
set -euo pipefail
echo "– unconfiguring nginx: $PROJECT_NAME on $API_DOMAIN"
sudo rm -f "/etc/nginx/apps/$API_DOMAIN/$PROJECT_NAME.conf"
sudo nginx -t
sudo systemctl reload nginx
EOF

echo "■ undeploying $PROJECT_NAME from $SSH_HOST using $ENV_FILE"
