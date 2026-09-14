<template>
  <div class="users-admin-page">
    <!-- U5 顶部：权限说明条 + 4 维 KPI 统计卡（对齐原型 admin-users.html 70-95） -->
    <div class="row-between">
      <div class="info-strip" style="margin: 0; padding: 6px 14px; border-radius: 8px">
        单一角色「成员（Member）」，全员同权。所有人均具备发起评测、数据集管理与调度观测能力。
      </div>
    </div>

    <div class="kpi-grid" style="--glow-c: var(--c-users)">
      <div class="kpi">
        <div class="kpi-num num">{{ users.length }}</div>
        <div class="kpi-label">成员总数</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num">{{ activeCount }}</div>
        <div class="kpi-label">正常使用</div>
      </div>
      <div class="kpi">
        <div class="kpi-num num" :style="disabledCount > 0 ? 'color: var(--accent-warning)' : ''">{{ disabledCount }}</div>
        <div class="kpi-label">已停用账号</div>
      </div>
      <div class="kpi">
        <!-- 契约（API.md）无登录活跃统计接口，无数据时显示 —，不虚构 -->
        <div class="kpi-num num">—</div>
        <div class="kpi-label">24h 登录活跃</div>
      </div>
    </div>

    <!-- U6 主内容双栏：左主栏成员列表 + 右 340px 安全监控侧栏 -->
    <div class="users-grid">
      <!-- 左主栏：成员列表与即时筛选 -->
      <div class="panel glow" style="--glow-c: var(--c-users)">
        <div class="panel-title">
          <div class="row">
            <span>平台成员账号列表</span>
            <span class="mono" style="font-size: 12px; color: var(--text-tertiary)">({{ filteredUsers.length }} / {{ users.length }} 个成员)</span>
          </div>

          <div class="row">
            <!-- 即时搜索与状态筛选（对齐原型 admin-users.html） -->
            <input
              v-model="searchKeyword"
              class="input"
              style="width: 200px"
              placeholder="搜索用户名…"
            />
            <select v-model="statusFilter" class="select" style="width: 120px">
              <option value="all">全部状态</option>
              <option value="active">正常</option>
              <option value="disabled">已停用</option>
            </select>
            <button class="btn btn-primary btn-sm" @click="showUserModal = true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
              <span>开通新成员</span>
            </button>

            <button class="btn btn-secondary btn-sm" :disabled="loading" @click="loadUsers">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="23 4 23 10 17 10"></polyline>
                <polyline points="1 20 1 14 7 14"></polyline>
                <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>
              </svg>
              <span>刷新</span>
            </button>
          </div>
        </div>

        <table class="ds-table">
          <thead>
            <tr>
              <th>成员信息</th>
              <th style="width: 130px">权限与角色</th>
              <th style="width: 110px">账号状态</th>
              <th style="width: 130px">最近登录 (IP)</th>
              <th style="width: 120px">开户时间</th>
              <th style="width: 150px; text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in filteredUsers" :key="u.id">
              <!-- U7 成员单元格双行结构：圆形头像 + 用户名 /（显示名·邮箱） -->
              <td>
                <div class="user-cell">
                  <div class="avatar-circle">{{ u.username.charAt(0).toUpperCase() }}</div>
                  <div class="user-name-box">
                    <span class="user-uname">{{ u.username }}</span>
                    <!-- 契约 AuthUser 暂无 display_name/email 字段，兜底展示「未完善资料」 -->
                    <span class="user-dname">{{ userSubText(u) }}</span>
                  </div>
                </div>
              </td>
              <td>
                <span class="tag-soft">成员 · 全员同权</span>
              </td>
              <td>
                <!-- U8 状态徽标：正常 succeeded / 停用 cancelled，均带呼吸点 -->
                <span v-if="!u.disabled" class="badge badge-succeeded"><i class="bdot"></i>正常</span>
                <span v-else class="badge badge-cancelled"><i class="bdot"></i>已停用</span>
              </td>
              <td class="small tertiary mono">
                <!-- 契约无 last_login_at/last_login_ip 字段，无数据显 — -->
                {{ lastLoginText(u) }}
              </td>
              <td class="mono" style="font-size: 12px; color: var(--text-tertiary)">
                {{ formatDate(u.created_at) }}
              </td>
              <td style="text-align: right">
                <div class="row" style="justify-content: flex-end; gap: 4px">
                  <button class="link-btn" @click="openResetPassword(u)">重置密码</button>
                  <button
                    class="link-btn"
                    :class="u.disabled ? '' : 'danger'"
                    @click="handleToggleStatus(u)"
                  >
                    {{ u.disabled ? '启用' : '停用' }}
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 右 340px 侧栏：AI 安全监控与审计流水（对齐原型 admin-users.html 157-214） -->
      <div class="section-gap" style="gap: 16px">
        <!-- 1. AI 账号安全与异常行为检测卡（mock 演示数据，契约无安全检测接口） -->
        <div class="ai-card">
          <div class="ai-card-head">
            <span class="ai-badge"><i class="ai-dot"></i>AI 账号异常检测</span>
          </div>
          <div class="section-gap" style="gap: 8px; margin-bottom: 10px">
            <div
              v-for="(line, i) in anomalyLines"
              :key="i"
              class="small ai-gen-line"
              style="color: var(--text-secondary); line-height: 1.5"
              :style="{ animationDelay: `${i * 90}ms` }"
              v-html="line"
            ></div>
          </div>
          <div class="row" style="justify-content: flex-end">
            <button class="btn btn-ai btn-sm" :disabled="locking" @click="handleAiLock">
              临时锁定 {{ ANOMALY_USERNAME }}
            </button>
          </div>
        </div>

        <!-- 2. 24h 登录活跃分布柱状图（内联 SVG 手绘 24 根柱；mock 演示数据） -->
        <div class="panel glow" style="--glow-c: var(--c-users); padding: 16px 18px">
          <div class="panel-title" style="margin-bottom: 8px">24h 登录活跃分布</div>
          <svg width="100%" height="72" viewBox="0 0 280 72" preserveAspectRatio="none" aria-hidden="true" style="margin-bottom: 8px">
            <rect
              v-for="(b, i) in loginBars"
              :key="i"
              :x="b.x"
              :y="b.y"
              :width="b.w"
              :height="b.h"
              rx="2"
              fill="var(--c-users)"
              :opacity="b.v ? 0.8 : 0.18"
            />
          </svg>
          <div class="row-between small">
            <span class="tertiary">登录成功 <b class="num" style="color: var(--accent-success)">{{ loginSuccessCount }} 次</b></span>
            <span class="tertiary">拦截失败 <b class="num" style="color: var(--accent-error)">3 次</b></span>
          </div>
        </div>

        <!-- 3. 近期合规审计轨迹时间线（静态示例数据 + 锁定操作实时追加） -->
        <div class="panel glow" style="--glow-c: var(--c-users); padding: 16px 18px">
          <div class="panel-title" style="margin-bottom: 12px">近期合规审计轨迹</div>
          <div class="timeline">
            <div v-for="(a, i) in auditLogs" :key="i" class="tl-item" :class="a.type">
              <div class="tl-time mono">{{ a.at }}</div>
              <div class="small">{{ a.text }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 弹窗 -->
    <UserModal
      v-model:show="showUserModal"
      @success="loadUsers"
    />

    <ResetPasswordModal
      v-model:show="showResetModal"
      :user="selectedUser"
      @success="loadUsers"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { api } from '../api/http'
import type { AuthUser } from '../api/types'
import UserModal from '../components/modals/UserModal.vue'
import ResetPasswordModal from '../components/modals/ResetPasswordModal.vue'
import { formatDate } from '../utils/format'

const message = useMessage()
const dialog = useDialog()

const users = ref<AuthUser[]>([])
const loading = ref(false)

// 搜索关键词与状态筛选（原型支持用户名/姓名/邮箱即时搜索，当前契约仅 username 字段）
const searchKeyword = ref('')
const statusFilter = ref<'all' | 'active' | 'disabled'>('all')

const filteredUsers = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  return users.value.filter(u => {
    if (kw && !u.username.toLowerCase().includes(kw)) return false
    if (statusFilter.value === 'active' && u.disabled) return false
    if (statusFilter.value === 'disabled' && !u.disabled) return false
    return true
  })
})

// U5 KPI：正常 / 已停用计数（成员总数直接取 users.length）
const activeCount = computed(() => users.value.filter(u => !u.disabled).length)
const disabledCount = computed(() => users.value.length - activeCount.value)

const showUserModal = ref(false)
const showResetModal = ref(false)
const selectedUser = ref<AuthUser | null>(null)

/** U7 成员副行文案：契约暂无 display_name/email，兜底「未完善资料」 */
function userSubText(u: AuthUser): string {
  const ext = u as AuthUser & { display_name?: string; email?: string }
  return ext.display_name || ext.email || '未完善资料'
}

/** U7 最近登录列：契约暂无 last_login_* 字段，无数据显 — */
function lastLoginText(u: AuthUser): string {
  const ext = u as AuthUser & { last_login_ip?: string; last_login_at?: string }
  if (!ext.last_login_at && !ext.last_login_ip) return '—'
  const ip = ext.last_login_ip || '—'
  const at = ext.last_login_at ? new Date(ext.last_login_at).toLocaleString('zh-CN', { hour12: false }) : ''
  return at ? `${ip} · ${at}` : ip
}

/* ─── U6 右栏：AI 异常检测 / 登录活跃柱图 / 审计轨迹（均为本地演示数据） ─── */

// AI 异常检测命中的演示账号（mock：契约无安全检测接口，仅作交互演示）
const ANOMALY_USERNAME = 'ops-li'
const locking = ref(false)

// 异常检测结论行（mock 演示文案，对齐原型）
const anomalyLines = ref<string[]>([
  `· 账号 <b>${ANOMALY_USERNAME}</b> 今晨 03:12 出现一次异地登录（IP: 198.51.100.22 归属地异常），平台安全网关已自动阻断。`,
  '· 其余成员账号登录频次正常，无暴力破解特征。',
])

// 24h 登录活跃逐时数据（mock 演示；契约无该统计接口）
const H24 = [0, 0, 1, 0, 0, 0, 1, 2, 5, 8, 6, 4, 3, 5, 7, 4, 3, 2, 1, 1, 0, 0, 0, 1]
const loginSuccessCount = H24.reduce((s, v) => s + v, 0)

/** 将 24 小时数据映射为 280x72 视窗内的 24 根柱（对齐原型 drawLoginBars） */
const loginBars = computed(() => {
  const max = Math.max(...H24, 1)
  const bw = 280 / 24
  return H24.map((v, i) => {
    const h = Math.max(2, (v / max) * 60)
    return {
      v,
      x: +(i * bw + 1.5).toFixed(1),
      y: +(68 - h).toFixed(1),
      w: +(bw - 3).toFixed(1),
      h: +h.toFixed(1),
    }
  })
})

// 合规审计轨迹（静态示例数据；锁定操作会向前追加）
interface AuditLog {
  at: string
  type: 'info' | 'warn' | 'err'
  text: string
}
const auditLogs = ref<AuditLog[]>([
  { at: '10:42', type: 'info', text: '重置密码 · ops-li (操作人: admin)' },
  { at: '09:18', type: 'info', text: '开户注册 · qa-wang (操作人: admin)' },
  { at: '08:50', type: 'warn', text: '冻结基线 · task e5f2b8 设为评测基准' },
  { at: '03:12', type: 'err', text: '异地登录拦截 · ops-li (IP: 198.51.100.22)' },
])

/** AI 临时锁定：对异常账号执行停用，写本地审计轨迹并 toast（对齐原型 ai-lock 交互） */
async function handleAiLock() {
  const target = users.value.find(x => x.username === ANOMALY_USERNAME)
  if (!target) {
    message.info(`演示账号 ${ANOMALY_USERNAME} 不存在于当前成员列表`)
    return
  }
  if (target.disabled) {
    message.info(`账号 ${ANOMALY_USERNAME} 当前已处于停用状态`)
    return
  }
  locking.value = true
  try {
    await api.users.toggleStatus(target.id, true)
    target.disabled = true
    // 写本地审计轨迹（前端演示；正式审计由后端落库）
    const now = new Date()
    const at = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    auditLogs.value.unshift({ at, type: 'warn', text: `AI 临时锁定 · ${ANOMALY_USERNAME} (操作人: admin)` })
    message.success(`账号 ${ANOMALY_USERNAME} 已临时锁定（写审计日志）`)
  } catch (err: any) {
    message.error(err.message || '临时锁定失败')
  } finally {
    locking.value = false
  }
}

async function loadUsers() {
  loading.value = true
  try {
    users.value = await api.users.list()
  } catch (err: any) {
    message.error(err.message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

function openResetPassword(user: AuthUser) {
  selectedUser.value = user
  showResetModal.value = true
}

function handleToggleStatus(user: AuthUser) {
  const targetDisabled = !user.disabled
  const actionText = targetDisabled ? '停用' : '启用'

  // 最后一名正常账号保护：停用后平台将无人可登录，直接拦截（对齐原型）
  if (targetDisabled && users.value.filter(u => !u.disabled).length <= 1) {
    message.error('最后一名正常账号不可停用')
    return
  }

  dialog.warning({
    title: `${actionText}用户「${user.username}」？`,
    content: targetDisabled
      ? '停用后该用户将无法登录平台，正在运行的任务仍将保留。'
      : '启用后该用户可恢复正常登录。',
    positiveText: `确认${actionText}`,
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.users.toggleStatus(user.id, targetDisabled)
        user.disabled = targetDisabled
        message.success(`已${actionText}该账号`)
      } catch (err: any) {
        message.error(err.message || `${actionText}失败`)
      }
    },
  })
}

onMounted(loadUsers)
</script>

<style scoped>
.users-admin-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* U6 双栏布局：左主栏 + 右 340px 侧栏（迁移自原型 .users-grid，侧栏宽度按任务要求 340px） */
.users-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 20px;
  align-items: flex-start;
}
@media (max-width: 1100px) {
  .users-grid {
    grid-template-columns: 1fr;
  }
}
/* U7 成员单元格：圆形头像 + 双行名称（迁移自原型 .avatar-circle / .user-cell） */
.avatar-circle {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--c-users) 20%, var(--bg-main));
  color: var(--c-users);
  font-weight: 700;
  font-size: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid color-mix(in srgb, var(--c-users) 40%, transparent);
  flex: 0 0 auto;
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-name-box {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.user-uname {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
}
.user-dname {
  font-size: 11px;
  color: var(--text-secondary);
}
/* 审计时间线 warn 类型节点色（base.css 仅定义 ok/err/info，此处补齐原型 warn 态） */
.tl-item.warn::before {
  border-color: var(--accent-warning);
}
</style>
