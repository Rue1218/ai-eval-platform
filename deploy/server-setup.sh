#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 服务器一次性初始化脚本（在服务器上以 root 运行一次）
# 适用：Ubuntu/Debian（apt）、CentOS/Rocky/Alma/阿里云 Linux（dnf/yum）
#
# 做什么：
#   1. 安装 Docker + Compose 插件
#   2. 创建 deploy 用户并加入 docker 组
#   3. 生成 SSH key（同一把 key 同时用于：GitHub Actions -> 服务器 和 服务器 -> GitHub 拉取）
#   4. 初始化应用目录并生成 .env
#
# 运行后需要手动完成（脚本末尾会提示）：
#   A. 把公钥加到 GitHub 仓库 Settings -> Deploy keys（只读）
#   B. 在 GitHub 仓库 Settings -> Secrets -> Actions 里配置 SSH_* 变量
# ============================================================

APP_DIR=/opt/ai-eval-platform
DEPLOY_USER=deploy
GIT_REPO=git@github.com:Rue1218/ai-eval-platform.git

if [ "$(id -u)" -ne 0 ]; then
    echo "请以 root 运行：sudo bash server-setup.sh"
    exit 1
fi

echo "==> [1/6] 安装 Docker"
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
else
    echo "Docker 已安装，跳过"
fi
systemctl enable --now docker

echo "==> [2/6] 创建 deploy 用户"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$DEPLOY_USER"
fi
usermod -aG docker "$DEPLOY_USER"

echo "==> [3/6] 生成 deploy 用户 SSH key"
if [ ! -f "/home/$DEPLOY_USER/.ssh/id_ed25519" ]; then
    sudo -u "$DEPLOY_USER" mkdir -p "/home/$DEPLOY_USER/.ssh"
    sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 -N "" -f "/home/$DEPLOY_USER/.ssh/id_ed25519" -C "$DEPLOY_USER@deploy"
fi
# 公钥加入 authorized_keys（允许 GitHub Actions 以 deploy 身份 SSH 进来）
PUBKEY=$(cat "/home/$DEPLOY_USER/.ssh/id_ed25519.pub")
if ! grep -qF "$PUBKEY" "/home/$DEPLOY_USER/.ssh/authorized_keys" 2>/dev/null; then
    echo "$PUBKEY" >> "/home/$DEPLOY_USER/.ssh/authorized_keys"
fi
chown -R "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh"
chmod 700 "/home/$DEPLOY_USER/.ssh"
chmod 600 "/home/$DEPLOY_USER/.ssh/authorized_keys"

# SSH over 443：国内访问 github.com 22/443 常被重置，走 ssh.github.com:443 更稳
if [ ! -f "/home/$DEPLOY_USER/.ssh/config" ]; then
    cat > "/home/$DEPLOY_USER/.ssh/config" <<EOF
Host github.com
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/id_ed25519
  IdentitiesOnly yes
EOF
    chown "$DEPLOY_USER:$DEPLOY_USER" "/home/$DEPLOY_USER/.ssh/config"
    chmod 600 "/home/$DEPLOY_USER/.ssh/config"
fi
# 信任 github.com 主机（走 443）
sudo -u "$DEPLOY_USER" ssh-keyscan ssh.github.com >> "/home/$DEPLOY_USER/.ssh/known_hosts" 2>/dev/null || true

echo "==> [4/6] 初始化应用目录"
mkdir -p "$APP_DIR"
chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"

echo "==> [5/6] 生成 .env"
if [ ! -f "$APP_DIR/.env" ]; then
    SECRET_KEY=$(openssl rand -hex 32)
    POSTGRES_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)
    KEY_ENCRYPTION_KEY=""
    if command -v python3 >/dev/null 2>&1; then
        KEY_ENCRYPTION_KEY=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
    fi
    cat > "$APP_DIR/.env" <<EOF
POSTGRES_USER=aieval
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
POSTGRES_DB=aieval
SECRET_KEY=$SECRET_KEY
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_PASSWORD=admin123
KEY_ENCRYPTION_KEY=$KEY_ENCRYPTION_KEY
ACCESS_TOKEN_EXPIRE_MINUTES=720
WS_TICKET_EXPIRE_MINUTES=5
WEB_PORT=80
API_PORT=8000
LIGHTRAG_PORT=9621
STRESS_PORT=19090
EOF
    chown "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/.env"
    echo "已生成 $APP_DIR/.env（请修改 BOOTSTRAP_ADMIN_PASSWORD）"
else
    echo ".env 已存在，跳过"
fi

echo "==> [6/6] 完成"

PUBKEY=$(cat "/home/$DEPLOY_USER/.ssh/id_ed25519.pub")
PRIVKEY="/home/$DEPLOY_USER/.ssh/id_ed25519"

cat <<MSG

============================================================
初始化完成！请手动完成以下两步：

A. 添加 GitHub Deploy Key（只读）：
   打开 https://github.com/Rue1218/ai-eval-platform/settings/keys
   点 "Add deploy key"，粘贴下面公钥，勾选 Allow write access 可不勾（只读即可）：

   $PUBKEY

B. 配置 GitHub Actions Secrets：
   打开 https://github.com/Rue1218/ai-eval-platform/settings/secrets/actions
   新增 4 个 Secret：

   SSH_HOST        服务器公网 IP
   SSH_USER        $DEPLOY_USER
   SSH_PORT        22
   SSH_PRIVATE_KEY 服务器上 $PRIVKEY 的完整内容（整段粘贴）

C. 首次部署（二选一）：
   - 在服务器执行：sudo -u $DEPLOY_USER bash $APP_DIR/deploy/deploy.sh
   - 或往仓库 main 分支推一次代码触发 GitHub Actions

   注意：SSH_PRIVATE_KEY 与服务器上 $PRIVKEY 是同一把私钥，
   公钥同时用于 Actions 登录服务器和服务器拉取仓库。
============================================================
MSG
