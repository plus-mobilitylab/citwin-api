#!/usr/bin/env bash
set -euo pipefail

ENVIRONMENT="${1:-}"
if [[ -z "$ENVIRONMENT" ]]; then
  echo "Usage: ./deploy.sh [environment]"
  echo "Example: ./deploy.sh prod"
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
  GIT_REPO_URL GIT_BRANCH
  API_DOMAIN API_PORT API_ROOT_PATH
)

for VAR in "${REQUIRED[@]}"; do
  [[ -n "${!VAR:-}" ]] || { echo "– missing required variable: $VAR"; exit 1; }
done

echo "□ deploying $PROJECT_NAME to $SSH_HOST using $ENV_FILE"

ssh_base=(ssh -p "$SSH_PORT" "$SSH_USER@$SSH_HOST")

remote_deploy() {
  "${ssh_base[@]}" "sudo -u '$DEPLOY_USER' -H /bin/bash -lc '/bin/bash -se'" </dev/stdin
}

# ----------------------------------------------------------------------------------------------------------------------
# git / project directory
# ----------------------------------------------------------------------------------------------------------------------

remote_deploy <<EOF
set -euo pipefail
if [[ ! -d "$DEPLOY_PATH/.git" ]]; then
  echo "– cloning branch: $GIT_BRANCH"
  mkdir -p "$DEPLOY_PATH"
  git clone -b "$GIT_BRANCH" "$GIT_REPO_URL" "$DEPLOY_PATH"
else
  echo "– pulling branch: $GIT_BRANCH"
  cd "$DEPLOY_PATH"
  git fetch origin "$GIT_BRANCH"
  git checkout -f "$GIT_BRANCH"
  git reset --hard "origin/$GIT_BRANCH"
  git clean -fd
fi
EOF

# ----------------------------------------------------------------------------------------------------------------------
# nginx
# ----------------------------------------------------------------------------------------------------------------------

remote_deploy <<EOF
set -euo pipefail
echo "– configuring nginx: $PROJECT_NAME on $API_DOMAIN"
sudo mkdir -p "/etc/nginx/apps/$API_DOMAIN"
sudo tee "/etc/nginx/apps/$API_DOMAIN/$PROJECT_NAME.conf" >/dev/null <<'NGINX'
location $API_ROOT_PATH/ {
    proxy_pass http://127.0.0.1:$API_PORT/;
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
NGINX
sudo nginx -t
sudo systemctl reload nginx
EOF

# ----------------------------------------------------------------------------------------------------------------------
# docker
# ----------------------------------------------------------------------------------------------------------------------

REMOTE_TMP="/tmp/.env.docker.$$.$RANDOM"

echo "– uploading env"
scp -P "$SSH_PORT" .env.docker "$SSH_USER@$SSH_HOST:$REMOTE_TMP"

remote_deploy <<EOF
set -euo pipefail
install -m 600 "$REMOTE_TMP" "$DEPLOY_PATH/.env.docker"
EOF

"${ssh_base[@]}" rm -f -- "$REMOTE_TMP"

remote_deploy <<EOF
set -euo pipefail
echo "– starting docker containers: $DEPLOY_PATH"
cd "$DEPLOY_PATH"
export PROJECT_NAME="$PROJECT_NAME"
export API_PORT="$API_PORT"
export API_ROOT_PATH="$API_ROOT_PATH"
docker compose down --volumes || true
docker compose up -d --build
EOF

echo "■ deploy: $PROJECT_NAME to $SSH_HOST using $ENV_FILE"
