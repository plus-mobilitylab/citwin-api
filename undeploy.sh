#!/usr/bin/env bash
set -e

ENVIRONMENT=$1
if [[ -z "$ENVIRONMENT" ]]; then
  echo "Usage: ./undeploy.sh [environment]"
  echo "Example: ./undeploy.sh prod"
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
REQUIRED=("PROJECT_NAME" "DEPLOY_USER" "DEPLOY_PORT" "DEPLOY_HOST" "DEPLOY_PATH" "API_PORT" "API_ROOT_PATH")
for VAR in "${REQUIRED[@]}"; do
  if [[ -z "${!VAR}" ]]; then
    echo "– missing required variable: $VAR"
    exit 1
  fi
done

echo "□ undeploying $PROJECT_NAME from $DEPLOY_HOST using $ENV_FILE"

ssh -p "$DEPLOY_PORT" "$DEPLOY_USER@$DEPLOY_HOST" bash << EOF
set -e

# docker
if [ -d "$DEPLOY_PATH" ]; then
  echo "- stopping docker containers: $DEPLOY_PATH"
  cd $DEPLOY_PATH
  export PROJECT_NAME="$PROJECT_NAME"
  export API_PORT="$API_PORT"
  export API_ROOT_PATH=$API_ROOT_PATH
  docker compose down --volumes || true

  echo "- removing project directory: $DEPLOY_PATH"
  sudo rm -rf $DEPLOY_PATH
fi

# nginx
echo "- unconfiguring nginx: $PROJECT_NAME"
sudo rm -f "/etc/nginx/conf.d/apps-enabled/$PROJECT_NAME.conf"
if sudo nginx -t; then
  sudo systemctl reload nginx
else
  echo "- nginx config test failed, not reloading"
fi

EOF

echo "■ undeploying $PROJECT_NAME from $DEPLOY_HOST using $ENV_FILE"
