#!/usr/bin/env bash
set -e

ENVIRONMENT=$1
if [[ -z "$ENVIRONMENT" ]]; then
  echo "Usage: ./deploy.sh [environment]"
  echo "Example: ./deploy.sh prod"
  exit 1
fi

# loading environment file
ENV_FILE=".env.deploy.$ENVIRONMENT"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "– environment file $ENV_FILE not found"
  exit 1
fi

# loading environment configuration
set -a
source "$ENV_FILE"
set +a


# ensuring required variables exist
REQUIRED=("PROJECT_NAME" "DEPLOY_USER" "DEPLOY_HOST" "DEPLOY_PORT" "DEPLOY_PATH" "GIT_REPO_URL" "GIT_BRANCH" "API_PORT" "API_ROOT_PATH")
for VAR in "${REQUIRED[@]}"; do
  if [[ -z "${!VAR}" ]]; then
    echo "– missing required variable: $VAR"
    exit 1
  fi
done

echo "□ deploying $PROJECT_NAME to $DEPLOY_HOST using $ENV_FILE"

ssh -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" bash << EOF
set -e

# git
if [ ! -d "$DEPLOY_PATH/.git" ]; then
  echo "– cloning branch: $GIT_BRANCH"
  git clone -b "$GIT_BRANCH" "$GIT_REPO_URL" "$DEPLOY_PATH"
else
  echo "– pulling branch: $GIT_BRANCH"
  cd "$DEPLOY_PATH"
  git fetch origin "$GIT_BRANCH"
  git checkout "$GIT_BRANCH"
  git reset --hard origin/"$GIT_BRANCH"
  git clean -fd
  git pull --tags
fi
EOF

echo "– uploading env for docker"
scp -P "$DEPLOY_PORT" .env.docker "$DEPLOY_USER@$DEPLOY_HOST:$DEPLOY_PATH/.env.docker"

ssh -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" bash << EOF
set -e

# nginx
echo "– configuring nginx: $PROJECT_NAME"
sudo mkdir -p /etc/nginx/conf.d/apps-enabled
EOF

ssh -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" "sudo tee /etc/nginx/conf.d/apps-enabled/$PROJECT_NAME.conf >/dev/null" << EOF
location $API_ROOT_PATH/ {
    proxy_pass http://localhost:$API_PORT/;
    proxy_redirect off;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
}
EOF

ssh -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" bash << EOF
if sudo nginx -t; then
  sudo systemctl reload nginx
else
  echo "- nginx config test failed, not reloading"
  exit 1
fi

# docker
echo "– starting docker containers: $DEPLOY_PATH"
cd "$DEPLOY_PATH"
export PROJECT_NAME="$PROJECT_NAME"
export API_PORT="$API_PORT"
export API_ROOT_PATH=$API_ROOT_PATH
docker compose down --volumes || true
docker compose up -d --build
EOF

echo "■ deploy: $PROJECT_NAME to $DEPLOY_HOST using $ENV_FILE"
