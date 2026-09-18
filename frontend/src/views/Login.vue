<template>
  <div class="login-wrapper" :style="parallaxStyle">
    <!-- 顶部状态栏浮动健康指示（保留免密健康探测） -->
    <div class="login-status-floating">
      <span class="status-badge">
        <span class="status-dot"></span>
        AGENT 后端
      </span>
      <span class="status-text">{{ agentStatusText }}</span>
    </div>

    <!-- 主双栏卡片容器 -->
    <div
      class="login-main-card scanline"
      :class="{
        'is-shaking': isShaking,
        'is-success-exit': isSuccessExit,
      }"
    >
      <!-- 左侧：AI 品牌介绍与科技插画区域（桌面端展示） -->
      <div class="login-left-pane">
        <!-- 品牌标识与版本 -->
        <div class="left-brand-row stagger-item stagger-1">
          <div class="brand-badge-box">
            <span class="brand-mark">A</span>
            <span class="brand-name">SECURE ACCESS</span>
          </div>
          <span class="brand-ver-tag" :title="buildTooltip">{{ buildTag }}</span>
        </div>

        <!-- 主标题 -->
        <h1 class="left-hero-title stagger-item stagger-2">
          <span class="ai-text">AI</span> 测试与评估平台
        </h1>

        <!-- 平台工作流简述 -->
        <p class="left-hero-desc stagger-item stagger-3">
          对话完成：用例（可选）→ Benchmark 和 / 或 RAG →（可选）压测 → 报告
        </p>

        <!-- 三大核心特性条目 -->
        <div class="left-feature-list">
          <div class="feature-item stagger-item stagger-4">
            <div class="feature-icon-wrap">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                <circle cx="9" cy="10" r="1"></circle>
                <circle cx="12" cy="10" r="1"></circle>
                <circle cx="15" cy="10" r="1"></circle>
              </svg>
            </div>
            <div class="feature-content">
              <h3 class="feature-title">智能对话驱动</h3>
              <p class="feature-desc">通过自然语言与 AI Agent 协作，自动完成测试流程与评估任务</p>
            </div>
          </div>

          <div class="feature-item stagger-item stagger-5">
            <div class="feature-icon-wrap">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="18" y1="20" x2="18" y2="10"></line>
                <line x1="12" y1="20" x2="12" y2="4"></line>
                <line x1="6" y1="20" x2="6" y2="14"></line>
              </svg>
            </div>
            <div class="feature-content">
              <h3 class="feature-title">多维度评估能力</h3>
              <p class="feature-desc">Benchmark、RAG、压测等多维度评估，全面覆盖测试场景</p>
            </div>
          </div>

          <div class="feature-item stagger-item stagger-6">
            <div class="feature-icon-wrap">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                <polyline points="9 12 11 14 15 10"></polyline>
              </svg>
            </div>
            <div class="feature-content">
              <h3 class="feature-title">安全可靠</h3>
              <p class="feature-desc">企业级安全防护，保障您的数据与隐私安全</p>
            </div>
          </div>
        </div>

        <!-- 底部 AI 3D 科技核心插画（带漂浮、呼吸与粒子微动） -->
        <div class="left-ai-graphic stagger-item stagger-7" :style="graphicParallaxStyle">
          <svg class="ai-svg" viewBox="0 0 340 180" fill="none" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <radialGradient id="baseGlow" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="#10b981" stop-opacity="0.22" />
                <stop offset="60%" stop-color="#34d399" stop-opacity="0.08" />
                <stop offset="100%" stop-color="#10b981" stop-opacity="0" />
              </radialGradient>
              <linearGradient id="cubeTop" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#d1fae5" stop-opacity="0.9" />
                <stop offset="100%" stop-color="#6ee7b7" stop-opacity="0.75" />
              </linearGradient>
              <linearGradient id="cubeLeft" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#10b981" stop-opacity="0.85" />
                <stop offset="100%" stop-color="#047857" stop-opacity="0.95" />
              </linearGradient>
              <linearGradient id="cubeRight" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#34d399" stop-opacity="0.9" />
                <stop offset="100%" stop-color="#059669" stop-opacity="0.9" />
              </linearGradient>
              <linearGradient id="baseTop" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#ffffff" stop-opacity="0.95" />
                <stop offset="100%" stop-color="#e6f4ea" stop-opacity="0.9" />
              </linearGradient>
              <radialGradient id="particleGlow" cx="35%" cy="35%" r="65%">
                <stop offset="0%" stop-color="#ecfdf5" />
                <stop offset="45%" stop-color="#34d399" />
                <stop offset="100%" stop-color="#047857" />
              </radialGradient>
            </defs>

            <!-- 底层科技光圈 -->
            <ellipse cx="170" cy="140" rx="140" ry="32" fill="url(#baseGlow)" class="ai-base-glow" />

            <!-- 左侧阶梯几何块 -->
            <g class="ai-step-blocks" opacity="0.85">
              <path d="M48 135 L80 119 L100 129 L68 145 Z" fill="#e2f3e9" stroke="#bbf0d4" stroke-width="1" />
              <path d="M48 135 L68 145 L68 152 L48 142 Z" fill="#c4eed6" />
              <path d="M68 145 L100 129 L100 136 L68 152 Z" fill="#9de3bd" />

              <path d="M72 110 L94 99 L108 106 L86 117 Z" fill="#d9f2e3" stroke="#bbf0d4" stroke-width="1" />
              <path d="M72 110 L86 117 L86 123 L72 116 Z" fill="#bfe9d0" />
              <path d="M86 117 L108 106 L108 112 L86 123 Z" fill="#98deb8" />
            </g>

            <!-- 核心底座平台 (呼吸动效) -->
            <g class="ai-base-pedestal">
              <path d="M120 148 L170 123 L220 148 L170 173 Z" fill="url(#baseTop)" stroke="#a7f3d0" stroke-width="1.5" />
              <path d="M120 148 L170 173 L170 180 L120 155 Z" fill="#9fe2be" />
              <path d="M170 173 L220 148 L220 155 L170 180 Z" fill="#6ee7b7" />

              <path d="M132 138 L170 119 L208 138 L170 157 Z" fill="#f0fdf4" stroke="#6ee7b7" stroke-width="1" />
              <path d="M132 138 L170 157 L170 162 L132 143 Z" fill="#a7f3d0" />
              <path d="M170 157 L208 138 L208 143 L170 162 Z" fill="#6ee7b7" />
            </g>

            <!-- AI 悬浮核心立方体 -->
            <g class="ai-core-cube">
              <path d="M170 48 L206 66 L170 84 L134 66 Z" fill="url(#cubeTop)" stroke="rgba(255,255,255,0.8)" stroke-width="1.2" />
              <path d="M134 66 L170 84 L170 126 L134 108 Z" fill="url(#cubeLeft)" stroke="rgba(255,255,255,0.4)" stroke-width="0.8" />
              <path d="M170 84 L206 66 L206 108 L170 126 Z" fill="url(#cubeRight)" stroke="rgba(255,255,255,0.4)" stroke-width="0.8" />
              
              <g transform="translate(170, 95) skewY(16) scale(0.9, 0.95)">
                <text x="-16" y="6" fill="#ffffff" font-family="'JetBrains Mono', 'Segoe UI', sans-serif" font-weight="900" font-size="20" letter-spacing="1">AI</text>
              </g>
              <path d="M170 48 L170 84" stroke="rgba(255, 255, 255, 0.9)" stroke-width="1.5" />
            </g>

            <!-- 装饰微粒（4个异步漂浮粒子） -->
            <circle cx="245" cy="98" r="6" fill="url(#particleGlow)" class="ai-particle ai-particle-1" />
            <circle cx="115" cy="54" r="4.5" fill="url(#particleGlow)" class="ai-particle ai-particle-2" />
            <circle cx="228" cy="46" r="3.5" fill="url(#particleGlow)" class="ai-particle ai-particle-3" />
            <circle cx="260" cy="132" r="5" fill="url(#particleGlow)" class="ai-particle ai-particle-4" />
          </svg>
        </div>
      </div>

      <!-- 右侧：登录操作面板 -->
      <div class="login-right-pane">
        <!-- 移动端专属品牌顶部栏（仅在窄屏下展示，保持平台品牌识别度） -->
        <div class="mobile-brand-header">
          <div class="mobile-brand-row">
            <div class="brand-badge-box">
              <span class="brand-mark">A</span>
              <span class="brand-name">SECURE ACCESS</span>
            </div>
            <span class="brand-ver-tag" :title="buildTooltip">{{ buildTag }}</span>
          </div>
          <h1 class="mobile-brand-title">
            <span class="ai-text">AI</span> 测试与评估平台
          </h1>
          <p class="mobile-brand-desc">
            基准评测 · 知识库 RAG · 自动化压测
          </p>
        </div>

        <!-- 欢迎标语 -->
        <div class="right-header">
          <h2 class="right-title">欢迎回来</h2>
          <p class="right-subtitle">登录您的 AI 测试与评估平台账号</p>
        </div>

        <!-- 登录模式切换 Tab -->
        <div class="tab-switch-container">
          <div
            class="tab-slider-indicator"
            :style="{ transform: activeTab === 'account' ? 'translateX(0%)' : 'translateX(100%)' }"
          ></div>
          <button
            class="tab-switch-btn"
            :class="{ 'is-active': activeTab === 'account' }"
            type="button"
            @click="switchTab('account')"
          >
            <svg class="tab-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
              <circle cx="12" cy="7" r="4"></circle>
            </svg>
            <span>账号密码登录</span>
          </button>
          <button
            class="tab-switch-btn"
            :class="{ 'is-active': activeTab === 'sso' }"
            type="button"
            @click="switchTab('sso')"
          >
            <svg class="tab-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
            </svg>
            <span>SSO 登录</span>
          </button>
        </div>

        <!-- Tab 内容切换过渡容器 -->
        <div class="tab-content-wrapper">
          <!-- 账号密码表单视图 -->
          <div v-show="activeTab === 'account'" class="tab-panel tab-panel-enter">
            <form class="login-form" @submit.prevent="submitLogin">
              <!-- 用户名输入框 -->
              <div class="form-field" :class="{ 'has-error': inputErrors.username }">
                <label class="field-label" for="login-username">用户名</label>
                <div class="input-shell" :class="{ 'is-focused': isUserFocused, 'is-filled': !!username }">
                  <span class="input-prefix-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>
                      <circle cx="12" cy="7" r="4"></circle>
                    </svg>
                  </span>
                  <input
                    id="login-username"
                    ref="usernameInputRef"
                    v-model="username"
                    type="text"
                    class="native-input"
                    placeholder="请输入用户名"
                    autocomplete="username"
                    :disabled="loading"
                    tabindex="1"
                    @focus="handleFieldFocus('user')"
                    @blur="handleFieldBlur('user')"
                    @input="clearFieldError('username')"
                    @keydown.enter="submitLogin"
                  />
                </div>
                <div v-if="inputErrors.username" class="field-error-text">
                  {{ inputErrors.username }}
                </div>
              </div>

              <!-- 密码输入框 -->
              <div class="form-field" :class="{ 'has-error': inputErrors.password }">
                <label class="field-label" for="login-password">密码</label>
                <div class="input-shell" :class="{ 'is-focused': isPassFocused, 'is-filled': !!password }">
                  <span class="input-prefix-icon">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                      <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                    </svg>
                  </span>
                  <input
                    id="login-password"
                    ref="passwordInputRef"
                    v-model="password"
                    :type="showPassword ? 'text' : 'password'"
                    class="native-input"
                    placeholder="请输入密码"
                    autocomplete="current-password"
                    :disabled="loading"
                    tabindex="2"
                    @focus="handleFieldFocus('pass')"
                    @blur="handleFieldBlur('pass')"
                    @input="clearFieldError('password')"
                    @keydown.enter="submitLogin"
                  />
                  <button
                    type="button"
                    class="password-toggle-btn"
                    tabindex="-1"
                    title="显示/隐藏密码"
                    @click="togglePasswordVisible"
                  >
                    <svg v-if="showPassword" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8z"></path>
                      <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                    <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                      <line x1="1" y1="1" x2="23" y2="23"></line>
                    </svg>
                  </button>
                </div>
                <div v-if="inputErrors.password" class="field-error-text">
                  {{ inputErrors.password }}
                </div>
              </div>

              <!-- 记住我与忘记密码 -->
              <div class="form-aux-row">
                <label class="remember-label" tabindex="3" @keydown.space.prevent="rememberMe = !rememberMe">
                  <input v-model="rememberMe" type="checkbox" class="native-checkbox" />
                  <span class="custom-checkbox" :class="{ 'is-checked': rememberMe }">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                  </span>
                  <span class="checkbox-text">记住我</span>
                </label>

                <button
                  type="button"
                  class="forgot-link-btn"
                  tabindex="4"
                  @click="showForgotModal = true"
                >
                  忘记密码？
                </button>
              </div>

              <!-- 统一全局登录错误提示 -->
              <div v-if="globalErrorMsg" class="login-error-banner">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10"></circle>
                  <line x1="12" y1="8" x2="12" y2="12"></line>
                  <line x1="12" y1="16" x2="12.01" y2="16"></line>
                </svg>
                <span>{{ globalErrorMsg }}</span>
              </div>

              <!-- 核心登录提交按钮 -->
              <button
                type="submit"
                class="login-submit-btn"
                :class="{
                  'is-loading': loading,
                  'is-success': isLoginSuccess,
                }"
                :disabled="loading || isLoginSuccess"
                tabindex="5"
              >
                <span v-if="!loading && !isLoginSuccess" class="btn-inner-text">
                  登 录
                </span>
                <span v-else-if="loading" class="btn-inner-loading">
                  <svg class="spinner-icon" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="rgba(255, 255, 255, 0.25)" stroke-width="3"></circle>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="#ffffff" stroke-width="3" stroke-linecap="round"></path>
                  </svg>
                  <span>{{ aiStepText }}</span>
                </span>
                <span v-else-if="isLoginSuccess" class="btn-inner-success">
                  <svg class="success-check-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                  <span>登录成功</span>
                </span>
              </button>
            </form>
          </div>

          <!-- SSO 登录视图 -->
          <div v-show="activeTab === 'sso'" class="tab-panel tab-panel-enter">
            <div class="sso-panel-content">
              <div class="sso-icon-badge">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                  <circle cx="12" cy="11" r="3"></circle>
                </svg>
              </div>
              <h3 class="sso-title">企业统一身份认证</h3>
              <p class="sso-desc">支持企业 OAuth2.0 / SAML 2.0 / 飞书 / 企业微信 快速单点登录</p>
              
              <button
                type="button"
                class="sso-submit-btn"
                :disabled="ssoLoading"
                @click="handleSsoLogin('Enterprise')"
              >
                <span v-if="!ssoLoading">使用企业账号一键登录</span>
                <span v-else class="btn-inner-loading">
                  <svg class="spinner-icon" viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="10" stroke="rgba(255, 255, 255, 0.25)" stroke-width="3"></circle>
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="#ffffff" stroke-width="3" stroke-linecap="round"></path>
                  </svg>
                  <span>正在建立 SSO 安全连接...</span>
                </span>
              </button>
            </div>
          </div>
        </div>

        <!-- 底部其他登录方式 -->
        <div class="social-divider">
          <span class="divider-line"></span>
          <span class="divider-text">其他登录方式</span>
          <span class="divider-line"></span>
        </div>

        <div class="social-login-row">
          <button
            type="button"
            class="social-btn"
            title="GitHub 登录"
            @click="handleSsoLogin('GitHub')"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
            </svg>
          </button>

          <button
            type="button"
            class="social-btn social-telegram"
            title="快捷协作接入"
            @click="handleSsoLogin('Telegram')"
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"></line>
              <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
            </svg>
          </button>

          <button
            type="button"
            class="social-btn"
            title="Google 账号登录"
            @click="handleSsoLogin('Google')"
          >
            <svg width="18" height="18" viewBox="0 0 24 24">
              <path fill="#EA4335" d="M12 5c1.6 0 3 .6 4.1 1.7l3.1-3.1C17.3 1.8 14.8 1 12 1 7.5 1 3.7 3.6 1.9 7.3l3.7 2.9C6.5 7.3 9 5 12 5z" />
              <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5c-.3 1.5-1.1 2.8-2.4 3.7l3.7 2.9c2.2-2 3.7-5.1 3.7-8.8z" />
              <path fill="#FBBC05" d="M5.6 14.8c-.2-.7-.4-1.5-.4-2.3 0-.8.2-1.6.4-2.3L1.9 7.3C.7 9.7 0 12.3 0 15.2c0 2.8.7 5.5 1.9 7.8l3.7-2.9z" />
              <path fill="#34A853" d="M12 23.5c3.2 0 6-1.1 8-3l-3.7-2.9c-1.1.7-2.5 1.2-4.3 1.2-3 0-5.5-2.3-6.4-5.2L1.9 16.5C3.7 20.2 7.5 23.5 12 23.5z" />
            </svg>
          </button>
        </div>

        <!-- 注册引导入口 -->
        <div class="register-prompt-row">
          <span>还没有账号？</span>
          <button type="button" class="register-link-btn" @click="showRegisterModal = true">立即注册</button>
        </div>
      </div>
    </div>

    <!-- 底部版权说明 -->
    <div class="login-page-footer">
      © 2024 Ai Test Platform. All rights reserved.
    </div>

    <!-- 弹窗 1：忘记密码 / 重置说明 -->
    <n-modal
      v-model:show="showForgotModal"
      preset="card"
      title="找回密码 / 账号指引"
      class="custom-dialog-modal"
      style="width: 480px; max-width: calc(100vw - 32px);"
    >
      <div class="dialog-content-body">
        <p class="dialog-p">本平台为内部评测系统，初始环境已内置以下演示账号（全员同权）：</p>
        <div class="account-pill-list">
          <div class="account-pill">
            <span class="pill-name">admin</span>
            <span class="pill-pwd">admin123</span>
            <span class="pill-tag">首登改密</span>
          </div>
          <div class="account-pill">
            <span class="pill-name">alice</span>
            <span class="pill-pwd">Alice123</span>
          </div>
          <div class="account-pill">
            <span class="pill-name">bob</span>
            <span class="pill-pwd">Bob12345</span>
          </div>
          <div class="account-pill">
            <span class="pill-name">boss</span>
            <span class="pill-pwd">Boss1234</span>
          </div>
        </div>
        <p class="dialog-sub-tip">如您已修改过个人密码并遗忘，请联系系统管理员或通过团队内部审批流申请重置。</p>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end">
          <n-button type="primary" @click="showForgotModal = false">知道了</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 弹窗 2：立即注册说明 -->
    <n-modal
      v-model:show="showRegisterModal"
      preset="card"
      title="账号申请与注册"
      class="custom-dialog-modal"
      style="width: 440px; max-width: calc(100vw - 32px);"
    >
      <div class="dialog-content-body">
        <p class="dialog-p">AI 测试与评估平台采用内部安全接入授权机制，不开放公网自助注册。</p>
        <p class="dialog-sub-tip">新成员加入请联系所在项目组 Leader 或平台管理员（admin）在「用户管理」模块分配权限账号。</p>
      </div>
      <template #footer>
        <div style="display: flex; justify-content: flex-end">
          <n-button type="primary" @click="showRegisterModal = false">好的</n-button>
        </div>
      </template>
    </n-modal>

  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage, NModal, NButton } from 'naive-ui'
import { useAuthStore } from '../stores/auth'

/** 路由与状态管理 */
const router = useRouter()
const message = useMessage()
const auth = useAuthStore()

/** 构建版本标识：短哈希 + 构建日期（北京时间），悬停查看完整信息 */
const buildCommit = __BUILD_VERSION__
const buildDate = new Date(__BUILD_TIME__)
const buildTimeLabel = Number.isNaN(buildDate.getTime())
  ? ''
  : buildDate.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai',
      hour12: false,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
const buildTag = buildTimeLabel ? `${buildCommit.slice(0, 8)} · ${buildTimeLabel.slice(5, 10)}` : buildCommit.slice(0, 8)
const buildTooltip = `前端构建\n版本：${buildCommit}\n构建时间：${buildTimeLabel || '未知'}（北京时间）`

/** 表单输入数据 */
const username = ref('admin')
const password = ref('admin123')
const rememberMe = ref(true)
const showPassword = ref(false)
const activeTab = ref<'account' | 'sso'>('account')

/** Focus 焦点状态 */
const isUserFocused = ref(false)
const isPassFocused = ref(false)

/** 验证与加载状态机 */
const loading = ref(false)
const isLoginSuccess = ref(false)
const isShaking = ref(false)
const isSuccessExit = ref(false)
const globalErrorMsg = ref('')
const aiStepText = ref('正在验证身份...')
const ssoLoading = ref(false)

/** 输入错误字段映射 */
const inputErrors = reactive({
  username: '',
  password: '',
})

/** DOM 引用 */
const usernameInputRef = ref<HTMLInputElement | null>(null)
const passwordInputRef = ref<HTMLInputElement | null>(null)

/** 弹窗控制 */
const showForgotModal = ref(false)
const showRegisterModal = ref(false)

/** 状态行：免密健康探测状态 */
const agentStatusText = ref('连接正常 · 调度器运行中')

/** 鼠标轻量视差偏移 (桌面端最大 ±3px) */
const mouseX = ref(0)
const mouseY = ref(0)

const parallaxStyle = computed(() => {
  return {
    '--parallax-x': `${mouseX.value}px`,
    '--parallax-y': `${mouseY.value}px`,
  }
})

const graphicParallaxStyle = computed(() => {
  return {
    transform: `translate3d(${mouseX.value * 2.5}px, ${mouseY.value * 2.5}px, 0)`,
  }
})

/** 处理鼠标轻量跟随计算 */
function handleMouseMove(e: MouseEvent) {
  if (window.innerWidth < 768) return // 移动端关闭视差
  const centerX = window.innerWidth / 2
  const centerY = window.innerHeight / 2
  const normX = (e.clientX - centerX) / centerX
  const normY = (e.clientY - centerY) / centerY
  mouseX.value = Math.max(-1, Math.min(1, normX))
  mouseY.value = Math.max(-1, Math.min(1, normY))
}

/** 切换 Tab */
function switchTab(tab: 'account' | 'sso') {
  activeTab.value = tab
  globalErrorMsg.value = ''
  clearFieldError('username')
  clearFieldError('password')
}

/** 焦点处理 */
function handleFieldFocus(type: 'user' | 'pass') {
  if (type === 'user') isUserFocused.value = true
  if (type === 'pass') isPassFocused.value = true
}

function handleFieldBlur(type: 'user' | 'pass') {
  if (type === 'user') isUserFocused.value = false
  if (type === 'pass') isPassFocused.value = false
}

/** 清理单个字段错误 */
function clearFieldError(field: 'username' | 'password') {
  inputErrors[field] = ''
  globalErrorMsg.value = ''
}

/** 密码显隐切换动画 */
function togglePasswordVisible() {
  showPassword.value = !showPassword.value
}

/** 登录页健康探测：未登录状态下调用免密健康接口 */
async function loadAgentStatus() {
  try {
    const res = await fetch('/api/health')
    if (res.ok) {
      agentStatusText.value = '连接正常 · 调度器运行中'
    }
  } catch {
    // 保持默认兜底文案
  }
}

/** 触发轻量震动反馈 */
function triggerShake() {
  isShaking.value = true
  setTimeout(() => {
    isShaking.value = false
  }, 220)
}

/** 阶段式 AI 验证模拟延时辅助函数 */
function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 核心登录提交 */
async function submitLogin() {
  let hasError = false
  const trimmedUser = username.value.trim()

  if (!trimmedUser) {
    inputErrors.username = '请输入用户名'
    hasError = true
  }
  if (!password.value) {
    inputErrors.password = '请输入密码'
    hasError = true
  }

  if (hasError) {
    triggerShake()
    nextTick(() => {
      if (!trimmedUser && usernameInputRef.value) {
        usernameInputRef.value.focus()
      } else if (!password.value && passwordInputRef.value) {
        passwordInputRef.value.focus()
      }
    })
    return
  }

  globalErrorMsg.value = ''
  loading.value = true
  isLoginSuccess.value = false
  aiStepText.value = '正在验证身份...'

  try {
    const loginPromise = auth.login(trimmedUser, password.value)
    await wait(320)

    aiStepText.value = '正在连接 Agent 服务...'
    const user = await loginPromise
    await wait(300)

    aiStepText.value = '正在加载工作空间...'
    await wait(280)

    loading.value = false
    isLoginSuccess.value = true
    message.success(`欢迎回来，${user.username}`)

    // V1.83 起机制废除：登录后直接进入系统，不再拦截强制改密。
    await wait(320)
    isSuccessExit.value = true
    await wait(300)
    router.push('/agent')
  } catch {
    loading.value = false
    isLoginSuccess.value = false
    globalErrorMsg.value = '用户名或密码错误，请重新输入'
    triggerShake()
  }
}

/** 模拟 SSO 快捷登录交互 */
async function handleSsoLogin(provider: string) {
  ssoLoading.value = true
  await wait(600)
  ssoLoading.value = false
  message.info(`已接收 ${provider} SSO 接入请求，请使用演示账号或联系管理员分配`)
}

onMounted(() => {
  loadAgentStatus()
  window.addEventListener('mousemove', handleMouseMove)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', handleMouseMove)
})
</script>

<style scoped>
/* ==========================================================================
   动画与设计令牌定义 (严格保持企业级科技绿与深空蓝配色体系)
   ========================================================================== */
:root {
  --motion-fast: 120ms;
  --motion-normal: 180ms;
  --motion-medium: 260ms;
  --motion-slow: 420ms;
  --ease-standard: cubic-bezier(0.4, 0, 0.2, 1);
  --ease-out: cubic-bezier(0, 0, 0.2, 1);
  --ease-in: cubic-bezier(0.4, 0, 1, 1);
}

/* 页面背景主容器：支持 100dvh 与响应式安全内边距 */
.login-wrapper {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  min-height: 100dvh;
  padding: clamp(16px, 3.5vh, 32px) 16px;
  background:
    radial-gradient(900px 520px at 12% -8%, rgba(16, 185, 129, 0.16), transparent 60%),
    radial-gradient(1100px 640px at 88% 108%, rgba(94, 234, 212, 0.18), transparent 62%),
    linear-gradient(158deg, #e7f4ec 0%, #f4f8f8 34%, #e9f5f0 58%, #eef7ec 82%, #e4f2ef 100%);
  background-attachment: fixed;
  animation: page-fade-in 400ms cubic-bezier(0, 0, 0.2, 1) forwards;
  overflow-x: hidden;
  box-sizing: border-box;
}

/* 浅绿色数据工程双层网格：缓慢移动模拟数据流动 */
.login-wrapper::before {
  content: '';
  position: absolute;
  inset: -40px;
  z-index: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(16, 185, 129, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(16, 185, 129, 0.08) 1px, transparent 1px),
    linear-gradient(rgba(16, 185, 129, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(16, 185, 129, 0.035) 1px, transparent 1px);
  background-size: 120px 120px, 120px 120px, 24px 24px, 24px 24px;
  animation: grid-flow 26s linear infinite;
}

@keyframes grid-flow {
  0% {
    background-position: 0 0, 0 0, 0 0, 0 0;
  }
  50% {
    background-position: 12px 16px, 12px 16px, 6px 8px, 6px 8px;
  }
  100% {
    background-position: 0 0, 0 0, 0 0, 0 0;
  }
}

@keyframes page-fade-in {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

/* 顶部状态浮条 */
.login-status-floating {
  position: absolute;
  top: 20px;
  right: 28px;
  z-index: 10;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(226, 232, 240, 0.85);
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  transition: all 180ms ease;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 10.5px;
  font-weight: 600;
  color: #059669;
  letter-spacing: 0.04em;
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 8px rgba(16, 185, 129, 0.8);
  animation: dot-pulse 2s infinite ease-in-out;
}

@keyframes dot-pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 0.85;
  }
  50% {
    transform: scale(1.35);
    opacity: 1;
  }
}

.status-text {
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  color: #64748b;
}

/* ==========================================================================
   主双栏卡片容器 (960px 宽度，圆角 24px)
   ========================================================================== */
.login-main-card {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  width: 960px;
  max-width: 100%;
  min-height: 560px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 24px;
  box-shadow:
    0 24px 64px -12px rgba(15, 23, 42, 0.1),
    0 2px 8px rgba(0, 0, 0, 0.03);
  overflow: hidden;
  animation: card-enter 450ms cubic-bezier(0.16, 1, 0.3, 1) 100ms both;
  transition: transform 180ms cubic-bezier(0.4, 0, 0.2, 1), opacity 300ms ease;
  box-sizing: border-box;
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.login-main-card.is-success-exit {
  opacity: 0;
  transform: translateY(-8px) scale(0.99);
}

.login-main-card.is-shaking {
  animation: card-shake 180ms cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
}

@keyframes card-shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-3px); }
  75% { transform: translateX(3px); }
}

.scanline::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 200px;
  pointer-events: none;
  background: linear-gradient(100deg, transparent, rgba(94, 234, 212, 0.15) 45%, rgba(16, 185, 129, 0.12) 58%, transparent);
  transform: translateX(-240px);
  animation: scan-x 6.5s cubic-bezier(0.4, 0, 0.2, 1) infinite 1s;
}

@keyframes scan-x {
  0% { transform: translateX(-240px); }
  50%, 100% { transform: translateX(1200px); }
}

/* ==========================================================================
   左侧品牌与特性展示区 (桌面端)
   ========================================================================== */
.login-left-pane {
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 44px 40px 32px 48px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.65) 0%, rgba(241, 245, 249, 0.4) 100%);
  border-right: 1px solid rgba(226, 232, 240, 0.65);
}

.stagger-item {
  animation: stagger-in 360ms cubic-bezier(0, 0, 0.2, 1) both;
}

.stagger-1 { animation-delay: 60ms; }
.stagger-2 { animation-delay: 140ms; }
.stagger-3 { animation-delay: 220ms; }
.stagger-4 { animation-delay: 300ms; }
.stagger-5 { animation-delay: 380ms; }
.stagger-6 { animation-delay: 460ms; }
.stagger-7 { animation-delay: 540ms; }

@keyframes stagger-in {
  from {
    opacity: 0;
    transform: translateX(-16px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.left-brand-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.brand-badge-box {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.brand-mark {
  display: inline-grid;
  place-items: center;
  width: 28px;
  height: 28px;
  background: #0f172a;
  color: #ffffff;
  font-family: var(--font-display, sans-serif);
  font-weight: 800;
  font-size: 15px;
  border-radius: 8px;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.15);
  transition: transform 180ms ease;
  user-select: none;
}

.brand-mark:hover {
  transform: scale(1.06);
}

.brand-name {
  font-family: var(--font-mono, monospace);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #0f172a;
}

.brand-ver-tag {
  display: inline-block;
  padding: 2px 8px;
  font-family: var(--font-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  color: #059669;
  background: rgba(16, 185, 129, 0.1);
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 999px;
}

.left-hero-title {
  font-size: 26px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 10px 0;
  letter-spacing: -0.01em;
  line-height: 1.25;
}

.ai-text {
  color: #10b981;
}

.left-hero-desc {
  font-size: 12.5px;
  color: #64748b;
  margin: 0 0 28px 0;
  line-height: 1.6;
}

.left-feature-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 24px;
}

.feature-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  transition: transform 180ms cubic-bezier(0.4, 0, 0.2, 1);
  cursor: default;
}

.feature-item:hover {
  transform: translateX(4px);
}

.feature-icon-wrap {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  background: #e6f7f0;
  color: #10b981;
  border-radius: 50%;
  transition: transform 180ms cubic-bezier(0.4, 0, 0.2, 1);
}

.feature-item:hover .feature-icon-wrap {
  transform: scale(1.06);
}

.feature-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.feature-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

.feature-desc {
  font-size: 11.5px;
  color: #64748b;
  margin: 0;
  line-height: 1.5;
}

.left-ai-graphic {
  position: relative;
  margin-top: auto;
  width: 100%;
  height: 150px;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  pointer-events: none;
  transition: transform 0.6s cubic-bezier(0.2, 0, 0.2, 1);
}

.ai-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.ai-core-cube {
  animation: ai-cube-float 5s ease-in-out infinite;
  transform-origin: center center;
}

@keyframes ai-cube-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}

.ai-base-pedestal {
  animation: ai-base-breathe 4s ease-in-out infinite;
}

@keyframes ai-base-breathe {
  0%, 100% { opacity: 0.94; }
  50% { opacity: 1; }
}

.ai-particle-1 { animation: particle-float-1 4s ease-in-out infinite; }
@keyframes particle-float-1 {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(4px, -6px); }
}

.ai-particle-2 { animation: particle-float-2 5s ease-in-out infinite; }
@keyframes particle-float-2 {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(-3px, -5px); }
}

.ai-particle-3 { animation: particle-float-3 6s ease-in-out infinite; }
@keyframes particle-float-3 {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(3px, -7px); }
}

.ai-particle-4 { animation: particle-float-4 7s ease-in-out infinite; }
@keyframes particle-float-4 {
  0%, 100% { transform: translate(0, 0); }
  50% { transform: translate(-4px, -4px); }
}

/* ==========================================================================
   右侧登录表单操作面板
   ========================================================================== */
.login-right-pane {
  display: flex;
  flex-direction: column;
  padding: 44px 44px 32px;
  background: #ffffff;
  box-sizing: border-box;
}

/* 移动端专属品牌顶部栏：桌面端默认隐藏 */
.mobile-brand-header {
  display: none;
  flex-direction: column;
  align-items: center;
  text-align: center;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px dashed #e2e8f0;
}

.mobile-brand-row {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.mobile-brand-title {
  font-size: 20px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 4px 0;
  letter-spacing: -0.01em;
}

.mobile-brand-desc {
  font-size: 11.5px;
  color: #64748b;
  margin: 0;
}

.right-header {
  margin-bottom: 20px;
}

.right-title {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 6px 0;
  letter-spacing: -0.01em;
}

.right-subtitle {
  font-size: 13px;
  color: #64748b;
  margin: 0;
}

/* Tab 切换容器 */
.tab-switch-container {
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 3px;
  background: #f1f5f9;
  border-radius: 12px;
  margin-bottom: 22px;
  border: 1px solid #e2e8f0;
}

.tab-slider-indicator {
  position: absolute;
  top: 3px;
  bottom: 3px;
  left: 3px;
  width: calc(50% - 3px);
  background: #ffffff;
  border-radius: 9px;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
  transition: transform 220ms cubic-bezier(0.4, 0, 0.2, 1);
  pointer-events: none;
}

.tab-switch-btn {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  min-height: 38px;
  font-size: 13px;
  font-weight: 500;
  color: #64748b;
  background: transparent;
  border: none;
  cursor: pointer;
  border-radius: 9px;
  transition: color 180ms ease, font-weight 180ms ease;
  user-select: none;
  -webkit-tap-highlight-color: transparent;
}

.tab-switch-btn.is-active {
  color: #059669;
  font-weight: 600;
}

.tab-icon {
  flex-shrink: 0;
}

.tab-content-wrapper {
  position: relative;
}

.tab-panel-enter {
  animation: panel-fade-in 200ms cubic-bezier(0, 0, 0.2, 1) both;
}

@keyframes panel-fade-in {
  from {
    opacity: 0;
    transform: translateX(8px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

/* 表单字段样式 */
.login-form {
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}

.input-shell {
  position: relative;
  display: flex;
  align-items: center;
  height: 44px;
  padding: 0 12px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.input-shell:hover {
  border-color: #cbd5e1;
}

.input-shell.is-focused {
  border-color: #10b981;
  box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.12);
}

.form-field.has-error .input-shell {
  border-color: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
}

.input-prefix-icon {
  display: grid;
  place-items: center;
  color: #94a3b8;
  margin-right: 8px;
  transition: opacity 160ms ease, transform 160ms ease, color 160ms ease;
  flex-shrink: 0;
}

.input-shell.is-focused .input-prefix-icon {
  color: #10b981;
  transform: scale(1.04);
}

.native-input {
  flex: 1;
  width: 100%;
  height: 100%;
  border: none;
  outline: none;
  background: transparent;
  font-size: 14px;
  color: #0f172a;
}

.native-input::placeholder {
  color: #94a3b8;
}

.password-toggle-btn {
  display: grid;
  place-items: center;
  background: transparent;
  border: none;
  color: #94a3b8;
  min-width: 36px;
  min-height: 36px;
  cursor: pointer;
  border-radius: 6px;
  transition: color 150ms ease, transform 160ms cubic-bezier(0.4, 0, 0.2, 1);
  -webkit-tap-highlight-color: transparent;
  flex-shrink: 0;
}

.password-toggle-btn:hover {
  color: #475569;
}

.password-toggle-btn:active {
  transform: scale(0.9);
}

.field-error-text {
  font-size: 12px;
  color: #ef4444;
  animation: error-slip-in 160ms cubic-bezier(0, 0, 0.2, 1) both;
}

@keyframes error-slip-in {
  from {
    opacity: 0;
    transform: translateY(-3px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 辅助操作行 */
.form-aux-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: -2px;
}

.remember-label {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  user-select: none;
  padding: 4px 0;
  -webkit-tap-highlight-color: transparent;
}

.native-checkbox {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.custom-checkbox {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  background: #ffffff;
  color: #ffffff;
  transition: transform 180ms cubic-bezier(0.34, 1.56, 0.64, 1), background-color 150ms ease, border-color 150ms ease;
  flex-shrink: 0;
}

.custom-checkbox.is-checked {
  background: #10b981;
  border-color: #10b981;
  transform: scale(1);
  animation: checkbox-pop 180ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

@keyframes checkbox-pop {
  0% { transform: scale(0.85); }
  50% { transform: scale(1.08); }
  100% { transform: scale(1); }
}

.checkbox-text {
  font-size: 12.5px;
  color: #64748b;
}

.forgot-link-btn {
  font-size: 12.5px;
  color: #10b981;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px 0;
  transition: opacity 150ms ease, transform 150ms ease;
  -webkit-tap-highlight-color: transparent;
}

.forgot-link-btn:hover {
  opacity: 0.85;
  transform: translateY(-1px);
}

.login-error-banner {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #ef4444;
  font-size: 12.5px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fee2e2;
  border-radius: 8px;
  animation: error-slip-in 160ms cubic-bezier(0, 0, 0.2, 1) both;
}

/* 核心登录按钮 */
.login-submit-btn {
  width: 100%;
  height: 44px;
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: 0.15em;
  margin-top: 4px;
  border-radius: 10px;
  background: #0f172a;
  color: #ffffff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
  transition: transform 160ms cubic-bezier(0.4, 0, 0.2, 1), background-color 160ms ease, box-shadow 160ms ease;
  -webkit-tap-highlight-color: transparent;
}

.login-submit-btn:hover:not(:disabled) {
  background: #1e293b;
  transform: translateY(-1px);
  box-shadow: 0 8px 20px -2px rgba(15, 23, 42, 0.2);
}

.login-submit-btn:active:not(:disabled) {
  transform: scale(0.985);
}

.login-submit-btn:disabled {
  cursor: not-allowed;
  opacity: 0.9;
}

.btn-inner-loading,
.btn-inner-success {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  letter-spacing: normal;
  font-size: 13.5px;
}

.spinner-icon {
  width: 16px;
  height: 16px;
  animation: spin 700ms linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.success-check-icon {
  width: 18px;
  height: 18px;
  stroke: #34d399;
  animation: check-scale-in 260ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

@keyframes check-scale-in {
  0% { transform: scale(0); }
  60% { transform: scale(1.15); }
  100% { transform: scale(1); }
}

/* SSO 面板样式 */
.sso-panel-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 16px 0;
}

.sso-icon-badge {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  background: #e6f7f0;
  border-radius: 50%;
  margin-bottom: 12px;
}

.sso-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 6px 0;
}

.sso-desc {
  font-size: 12px;
  color: #64748b;
  margin: 0 0 20px 0;
  line-height: 1.5;
  max-width: 280px;
}

.sso-submit-btn {
  width: 100%;
  height: 44px;
  font-size: 14px;
  font-weight: 600;
  border-radius: 10px;
  background: #10b981;
  color: #ffffff;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2);
  transition: background-color 160ms ease, transform 160ms ease;
  -webkit-tap-highlight-color: transparent;
}

.sso-submit-btn:hover:not(:disabled) {
  background: #059669;
  transform: translateY(-1px);
}

.sso-submit-btn:active:not(:disabled) {
  transform: scale(0.985);
}

/* 社交登录分割线 */
.social-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 22px 0 16px;
}

.divider-line {
  flex: 1;
  height: 1px;
  background: #e2e8f0;
}

.divider-text {
  font-size: 12px;
  color: #94a3b8;
}

.social-login-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
}

.social-btn {
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  color: #334155;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.02);
  transition: transform 180ms cubic-bezier(0.4, 0, 0.2, 1), border-color 180ms ease, box-shadow 180ms ease;
  -webkit-tap-highlight-color: transparent;
}

.social-btn:hover {
  transform: translateY(-3px) scale(1.05);
  border-color: #cbd5e1;
  box-shadow: 0 6px 14px -2px rgba(15, 23, 42, 0.08);
}

.social-btn:active {
  transform: scale(0.94);
}

.social-telegram {
  color: #0284c7;
}

/* 注册引导行 */
.register-prompt-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 12.5px;
  color: #64748b;
  margin-top: 20px;
}

.register-link-btn {
  background: transparent;
  border: none;
  color: #10b981;
  font-weight: 600;
  cursor: pointer;
  padding: 4px;
  transition: opacity 150ms ease;
  -webkit-tap-highlight-color: transparent;
}

.register-link-btn:hover {
  opacity: 0.85;
}

.login-page-footer {
  margin-top: 24px;
  font-size: 12px;
  color: #64748b;
  text-align: center;
}

/* 弹窗样式 */
.custom-dialog-modal {
  border-radius: 16px;
}

.dialog-content-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dialog-p {
  font-size: 13px;
  color: #334155;
  margin: 0;
  line-height: 1.6;
}

.dialog-sub-tip {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
  line-height: 1.5;
}

.account-pill-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin: 4px 0;
}

.account-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
}

.pill-name {
  font-weight: 600;
  color: #0f172a;
}

.pill-pwd {
  color: #64748b;
}

.pill-tag {
  font-size: 10px;
  padding: 1px 5px;
  background: #e6f7f0;
  color: #059669;
  border-radius: 4px;
}

.req-star {
  color: #ef4444;
}

/* ==========================================================================
   移动端与平板多级响应式适配 (Mobile Responsive Breakpoints)
   ========================================================================== */

/* 平板 & 窄屏桌面 (<= 900px)：收起左侧宽栏，显示移动端顶部品牌标识 */
@media (max-width: 900px) {
  .login-main-card {
    grid-template-columns: 1fr;
    width: 480px;
    max-width: 100%;
    min-height: auto;
    border-radius: 20px;
  }
  .login-left-pane {
    display: none;
  }
  .mobile-brand-header {
    display: flex;
  }
  .login-right-pane {
    padding: 32px 32px 28px;
  }
  .login-status-floating {
    top: 16px;
    right: 20px;
  }
}

/* 手机端 (<= 640px)：精细化触控尺寸与安全间距适配 */
@media (max-width: 640px) {
  .login-wrapper {
    padding: 16px 12px;
    justify-content: flex-start;
  }
  .login-status-floating {
    position: static;
    margin-bottom: 14px;
    align-self: center;
    padding: 3px 10px;
  }
  .login-main-card {
    width: 100%;
    max-width: 440px;
    border-radius: 18px;
    box-shadow:
      0 12px 32px -8px rgba(15, 23, 42, 0.08),
      0 2px 6px rgba(0, 0, 0, 0.02);
  }
  .login-right-pane {
    padding: 24px 20px 22px;
  }
  .mobile-brand-header {
    margin-bottom: 16px;
    padding-bottom: 14px;
  }
  .mobile-brand-title {
    font-size: 19px;
  }
  .right-header {
    margin-bottom: 16px;
    text-align: center;
  }
  .right-title {
    font-size: 22px;
  }
  .tab-switch-container {
    margin-bottom: 18px;
  }
  .tab-switch-btn {
    min-height: 40px;
    font-size: 13px;
  }
  .input-shell {
    height: 46px;
  }
  .native-input {
    font-size: 15px;
  }
  .login-submit-btn,
  .sso-submit-btn {
    height: 46px;
    font-size: 15px;
  }
  .social-divider {
    margin: 18px 0 14px;
  }
  .social-login-row {
    gap: 14px;
  }
  .social-btn {
    width: 42px;
    height: 42px;
  }
  .register-prompt-row {
    margin-top: 16px;
  }
  .login-page-footer {
    margin-top: 18px;
    font-size: 11px;
  }
}

/* 超窄屏手机 (<= 380px)：极窄视口紧凑排版 */
@media (max-width: 380px) {
  .login-wrapper {
    padding: 12px 8px;
  }
  .login-right-pane {
    padding: 20px 14px 18px;
  }
  .mobile-brand-title {
    font-size: 17.5px;
  }
  .right-title {
    font-size: 20px;
  }
  .tab-switch-btn {
    font-size: 12px;
    gap: 4px;
    padding: 6px 8px;
  }
  .account-pill-list {
    grid-template-columns: 1fr;
  }
}
</style>
