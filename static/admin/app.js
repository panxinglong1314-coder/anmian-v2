const API_BASE = '/api/v1/admin';
let adminToken = localStorage.getItem('admin_token') || '';
let refreshTimer = null;
let chartInstances = {};
let healthInterval = null;

// 缓存用户列表数据用于前端搜索/分页
let usersCache = [];
let usersPage = 1;
const USERS_PER_PAGE = 10;

// ========== Toast 通知 ==========

function toast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ';
  el.innerHTML = `<span>${icon}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'toastOut .3s ease forwards';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ========== Modal ==========

function showModal(content) {
  const modal = document.getElementById('suggestion-modal');
  document.getElementById('suggestion-modal-body').textContent = content;
  modal.classList.remove('hidden');
}

function hideModal() {
  document.getElementById('suggestion-modal').classList.add('hidden');
}

function closeModal(e) {
  if (e.target === e.currentTarget) hideModal();
}

// ========== Loading 状态 ==========

function setLoading(id, loading) {
  const btn = document.getElementById(id);
  if (!btn) return;
  const original = btn.dataset.original || btn.textContent;
  if (!btn.dataset.original) btn.dataset.original = original;
  btn.textContent = loading ? '⏳ 处理中...' : original;
  btn.disabled = loading;
}

// ========== 认证 ==========

function checkAuth() {
  if (adminToken) {
    document.getElementById('login-page').classList.add('hidden');
    document.getElementById('main-app').classList.remove('hidden');
    document.getElementById('main-app').style.display = 'flex';
    loadDashboard(7);
    startAutoRefresh();
    startHealthCheck();
  } else {
    document.getElementById('login-page').classList.remove('hidden');
    document.getElementById('main-app').classList.add('hidden');
    document.getElementById('main-app').style.display = 'none';
    stopHealthCheck();
  }
}

async function doLogin() {
  const input = document.getElementById('login-input');
  const token = input.value.trim();
  if (!token) return;
  try {
    const r = await fetch('/api/v1/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token })
    });
    const data = await r.json();
    if (data.success) {
      adminToken = token;
      localStorage.setItem('admin_token', token);
      toast('登录成功', 'success');
      checkAuth();
    } else {
      document.getElementById('login-error').classList.remove('hidden');
      toast('密码错误', 'error');
    }
  } catch (e) {
    document.getElementById('login-error').classList.remove('hidden');
    toast('登录失败: ' + e.message, 'error');
  }
}

function logout() {
  adminToken = '';
  localStorage.removeItem('admin_token');
  stopAutoRefresh();
  stopHealthCheck();
  checkAuth();
  document.getElementById('login-input').value = '';
  toast('已退出登录', 'info');
}

// ========== 健康检查轮询 ==========

function startHealthCheck() {
  stopHealthCheck();
  checkHealth();
  healthInterval = setInterval(checkHealth, 60000); // 每分钟
}

function stopHealthCheck() {
  if (healthInterval) clearInterval(healthInterval);
}

async function checkHealth() {
  const dot = document.getElementById('health-dot');
  const label = document.getElementById('health-label');
  if (!dot || !label) return;
  try {
    const r = await fetch('/api/v1/admin/health');
    const data = await r.json();
    if (data.status === 'healthy') {
      dot.className = 'dot dot-green';
      label.textContent = '正常';
    } else {
      dot.className = 'dot dot-red';
      label.textContent = '异常';
    }
  } catch (e) {
    dot.className = 'dot dot-red';
    label.textContent = '离线';
  }
}

// ========== 请求封装 ==========

async function fetchJSON(url) {
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (adminToken) headers['X-Admin-Token'] = adminToken;
    const r = await fetch(url, { headers });
    if (r.status === 401) { logout(); toast('认证已过期', 'error'); return { error: '未授权' }; }
    return await r.json();
  } catch (e) {
    toast('请求失败: ' + e.message, 'error');
    return { error: e.message };
  }
}

// ========== CSV 导出 ==========

async function downloadCSV(type) {
  const btnId = type === 'safety' ? 'btn-export-safety' : type === 'evaluations' ? 'btn-exportquality' : 'btn-export-users';
  setLoading(btnId, true);
  const days = document.getElementById('export-days')?.value || 30;
  const url = `${API_BASE}/export/${type}?days=${days}`;
  try {
    const headers = {};
    if (adminToken) headers['X-Admin-Token'] = adminToken;
    const r = await fetch(url, { headers });
    if (r.status === 401) { logout(); toast('认证已过期', 'error'); return; }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${type}_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    toast('导出成功', 'success');
  } catch (e) { toast('导出失败: ' + e.message, 'error'); }
  finally { setLoading(btnId, false); }
}

// ========== 页面路由 ==========

const pageTitles = {
  dashboard: '仪表盘',
  safety: '安全中心',
  quality: 'AI 质量监控',
  users: '用户列表',
  health: '服务器监控',
  retention: '留存分析',
};

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  document.getElementById('page-' + name).classList.remove('hidden');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const nav = document.querySelector(`[data-page="${name}"]`);
  if (nav) nav.classList.add('active');
  document.getElementById('page-title').textContent = pageTitles[name] || name;
  if (name === 'dashboard') loadDashboard(7);
  if (name === 'safety') loadSafety();
  if (name === 'quality') loadQuality();
  if (name === 'users') loadUsers();
  if (name === 'health') loadHealth();
  if (name === 'retention') loadRetention();
}

// ========== 自动刷新 ==========

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(() => {
    const active = document.querySelector('.nav-item.active');
    if (!active) return;
    const page = active.dataset.page;
    if (page === 'dashboard') loadDashboard(7);
    if (page === 'safety') loadSafety();
    if (page === 'quality') loadQuality();
    if (page === 'users') loadUsers();
    if (page === 'health') loadHealth();
    if (page === 'retention') loadRetention();
  }, 300000);
}

function stopAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = null;
}

// ========== 空状态 ==========

function emptyStateHTML(title, desc, icon = '📭') {
  return `<div class="empty-state"><div class="empty-state-icon">${icon}</div><div class="empty-state-title">${title}</div><div class="empty-state-desc">${desc}</div></div>`;
}

// ========== 趋势箭头 ==========

function trendBadge(delta) {
  if (delta === null || delta === undefined) return '<span class="text-gray-400 text-xs">--</span>';
  const sign = delta > 0 ? '+' : '';
  const cls = delta > 0 ? 'text-green-600' : delta < 0 ? 'text-red-500' : 'text-gray-400';
  const arrow = delta > 0 ? '↑' : delta < 0 ? '↓' : '→';
  return `<span class="${cls} text-xs font-medium ml-1">${arrow}${sign}${delta}%</span>`;
}

// ========== 仪表盘 ==========

let currentDashboardDays = 7;

function setMetricCard(id, value, sub, barPercent, barColor) {
  document.getElementById(id).textContent = value;
  const subEl = document.getElementById(id + '-sub');
  if (subEl) subEl.textContent = sub;
  const bar = document.getElementById(id + '-bar');
  if (bar) { bar.style.width = barPercent + '%'; if (barColor) bar.style.background = barColor; }
}

async function loadDashboard(days) {
  currentDashboardDays = days;
  document.querySelectorAll('#page-dashboard .tab-btn').forEach(t => t.classList.remove('active'));
  const tab = document.getElementById('tab-d-' + days);
  if (tab) tab.classList.add('active');

  const data = await fetchJSON(`${API_BASE}/dashboard?days=${days}`);
  const hasData = data && !data.error && !data.message;

  if (!hasData) {
    setMetricCard('d-active-users', '--', '暂无数据', 0, '#3b82f6');
    setMetricCard('d-sessions', '--', '暂无数据', 0, '#8b5cf6');
    setMetricCard('d-avg-turns', '--', '暂无数据', 0, '#10b981');
    setMetricCard('d-avg-duration', '--', '暂无数据', 0, '#6366f1');
    setMetricCard('d-night-ratio', '--', '暂无数据', 0, '#f59e0b');
    setMetricCard('d-avg-rating', '--', '暂无数据', 0, '#ef4444');
    renderChart('chart-rating-dist', null, emptyStateHTML('暂无评级数据', '当前时间范围内暂无会话评估记录', '📊'));
    renderChart('chart-outcome', null, emptyStateHTML('暂无结局数据', '当前时间范围内暂无会话记录', '📈'));
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    return;
  }

  const total = data.total_sessions || 0;
  const trend = data.trend || {};
  setMetricCard('d-active-users', data.active_users ?? 0,
    `共 ${total} 会话 ${trendBadge(trend.users_delta)}`, Math.min((data.active_users || 0) / Math.max(total, 1) * 100, 100), '#3b82f6');
  setMetricCard('d-sessions', total,
    `环比 ${trendBadge(trend.sessions_delta)}`, Math.min(total / 50 * 100, 100), '#8b5cf6');
  setMetricCard('d-avg-turns', data.avg_turns_per_session ?? 0, '每会话平均轮次', Math.min((data.avg_turns_per_session || 0) / 20 * 100, 100), '#10b981');
  // ✅ 修复: avg_duration_min 直接使用（不再硬编码0）
  setMetricCard('d-avg-duration', data.avg_duration_min || 0, '平均会话时长(分钟)', Math.min((data.avg_duration_min || 0) / 60 * 100, 100), '#6366f1');
  // ✅ 修复: night_ratio 直接是百分比数值（如 5.5 表示 5.5%），不再 ×100
  setMetricCard('d-night-ratio', (data.night_ratio ?? 0) + '%', '22:00-06:00 占比', Math.min(data.night_ratio ?? 0, 100), '#f59e0b');
  const rating = data.user_rating_avg;
  setMetricCard('d-avg-rating', rating ?? '--', rating ? `满分 5.0` : '暂无评分', rating ? (rating / 5 * 100) : 0, '#ef4444');

  // 评级分布饼图
  const dist = data.rating_distribution || {};
  const totalRated = Object.values(dist).reduce((a, b) => a + b, 0);
  if (totalRated === 0) {
    renderChart('chart-rating-dist', null, emptyStateHTML('暂无评级数据', '当前时间范围内暂无已评估的会话', '📊'));
  } else {
    renderChart('chart-rating-dist', {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 12 } },
      series: [{
        type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
        avoidLabelOverlap: true,
        label: { show: true, formatter: '{b}\n{c}', fontSize: 11 },
        labelLine: { show: true },
        data: [
          { value: dist['🟢优秀'] || 0, name: '优秀', itemStyle: { color: '#22c55e' } },
          { value: dist['🟡良好'] || 0, name: '良好', itemStyle: { color: '#eab308' } },
          { value: dist['🟠需改进'] || 0, name: '需改进', itemStyle: { color: '#f97316' } },
          { value: dist['🔴不合格'] || 0, name: '不合格', itemStyle: { color: '#ef4444' } },
        ]
      }]
    });
  }

  // 会话结局柱状图
  const outcomes = data.outcome_distribution || {};
  if (Object.keys(outcomes).length === 0) {
    renderChart('chart-outcome', null, emptyStateHTML('暂无结局数据', '当前时间范围内暂无会话记录', '📈'));
  } else {
    renderChart('chart-outcome', {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: Object.keys(outcomes), axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', data: Object.values(outcomes), itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] }, barWidth: '50%' }]
    });
  }

  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

// ========== 安全中心 ==========

async function loadSafety() {
  const data = await fetchJSON(`${API_BASE}/safety?days=30`);
  const events = Array.isArray(data) ? data : [];

  const total = events.length;
  const missed = events.filter(e => e.crisis_status === '漏报').length;
  const bad = events.filter(e => e.bad_advice_found).length;
  const pass = events.filter(e => e.safety_pass).length;

  document.getElementById('s-total').textContent = total || events.length;
  document.getElementById('s-missed').textContent = missed;
  document.getElementById('s-bad').textContent = bad;
  document.getElementById('s-pass').textContent = total > 0 ? (pass + (events.length - missed - bad)) : (events.length);

  const tbody = document.getElementById('safety-table');
  tbody.innerHTML = '';
  if (!events.length) {
    tbody.innerHTML = `<tr><td colspan="6">${emptyStateHTML('暂无安全事件', '最近30天内未检测到安全相关事件', '🛡️')}</td></tr>`;
    return;
  }
  events.forEach(e => {
    const tr = document.createElement('tr');
    const cs = e.crisis_status;
    let badge = 'badge-green', text = '正常';
    if (cs === '已识别') { badge = 'badge-yellow'; text = '已识别'; }
    else if (cs === '已处理') { badge = 'badge-blue'; text = '已处理'; }
    else if (cs === '漏报') { badge = 'badge-red'; text = '漏报'; }
    const badBadge = e.bad_advice_found
      ? '<span class="badge badge-red"><span class="dot dot-red"></span>是</span>'
      : '<span class="badge badge-green"><span class="dot dot-green"></span>否</span>';
    const suggestion = (e.top_suggestion || '暂无').replace(/"/g, '&quot;').replace(/'/g, "\\'");
    tr.innerHTML = `
      <td>${(e.timestamp || '').slice(0, 16)}</td>
      <td><span class="truncate-id font-mono text-xs text-gray-500">${e.user_id || '--'}</span></td>
      <td><span class="badge ${badge}">${text}</span></td>
      <td>${badBadge}</td>
      <td>${e.overall_rating || '<span class="text-gray-400">--</span>'}</td>
      <td><button class="text-blue-600 text-xs hover:underline" onclick="showModal('${suggestion}')">查看建议</button></td>
    `;
    tbody.appendChild(tr);
  });
}

// ========== AI 质量 ==========

function formatScore(value, max, label) {
  if (value === undefined || value === null || value === '--') return { text: '--', pct: 0, sub: '暂无数据' };
  const num = parseFloat(value);
  const pct = Math.min((num / max) * 100, 100);
  return { text: num.toFixed(1), pct, sub: `${label} · ${num.toFixed(1)}/${max}` };
}

async function loadQuality() {
  const data = await fetchJSON(`${API_BASE}/quality?days=30`);
  const hasData = data && !data.error && !data.message;

  if (!hasData) {
    setMetricCard('q-empathy', '--', '暂无数据', 0, '#8b5cf6');
    setMetricCard('q-tech', '--', '暂无数据', 0, '#06b6d4');
    setMetricCard('q-coherence', '--', '暂无数据', 0, '#10b981');
    renderChart('chart-empathy-dist', null, emptyStateHTML('暂无共情数据', '当前时间范围内暂无评估记录', '📊'));
    renderChart('chart-tech-dist', null, emptyStateHTML('暂无技术有效性数据', '当前时间范围内暂无评估记录', '📊'));
    document.getElementById('quality-failures').innerHTML = emptyStateHTML('数据积累中', '预计 10 条会话后展示高频失败模式', '🔧');
    return;
  }

  const emp = formatScore(data.empathy?.mean, 5, '共情');
  setMetricCard('q-empathy', emp.text, emp.sub, emp.pct, '#8b5cf6');
  const tech = formatScore(data.technical?.mean, 9, '技术有效性');
  setMetricCard('q-tech', tech.text, tech.sub, tech.pct, '#06b6d4');
  const coh = formatScore(data.coherence?.mean, 5, '连贯性');
  setMetricCard('q-coherence', coh.text, coh.sub, coh.pct, '#10b981');

  const empDist = data.empathy?.distribution || {};
  const empTotal = Object.values(empDist).reduce((a, b) => a + b, 0);
  if (empTotal === 0) {
    renderChart('chart-empathy-dist', null, emptyStateHTML('暂无共情分布数据', '当前时间范围内暂无评估记录', '📊'));
  } else {
    renderChart('chart-empathy-dist', {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: ['0','1','2','3','4','5'], axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', data: [0,1,2,3,4,5].map(i => empDist[String(i)] || 0), itemStyle: { color: '#8b5cf6', borderRadius: [4,4,0,0] }, barWidth: '50%' }]
    });
  }

  const techDist = data.technical?.distribution || {};
  const techTotal = Object.values(techDist).reduce((a, b) => a + b, 0);
  if (techTotal === 0) {
    renderChart('chart-tech-dist', null, emptyStateHTML('暂无技术有效性分布数据', '当前时间范围内暂无评估记录', '📊'));
  } else {
    renderChart('chart-tech-dist', {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: ['0','1','2','3','4','5','6','7','8','9'], axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', data: [0,1,2,3,4,5,6,7,8,9].map(i => techDist[String(i)] || 0), itemStyle: { color: '#06b6d4', borderRadius: [4,4,0,0] }, barWidth: '50%' }]
    });
  }

  const failures = data.top_failure_modes || [];
  const fDiv = document.getElementById('quality-failures');
  fDiv.innerHTML = failures.length ? failures.map((f, i) => `
    <div class="flex items-center justify-between py-2.5 ${i < failures.length - 1 ? 'border-b border-gray-100' : ''}">
      <div class="flex items-center gap-3">
        <span class="w-5 h-5 rounded bg-gray-100 text-gray-500 text-xs flex items-center justify-center font-medium">${i + 1}</span>
        <span class="text-sm text-gray-700">${f.issue}</span>
      </div>
      <span class="text-xs font-medium text-gray-500 bg-gray-100 px-2 py-0.5 rounded">${f.count} 次</span>
    </div>
  `).join('') : emptyStateHTML('数据积累中', '预计 10 条会话后展示高频失败模式', '🔧');
}

// ========== 用户管理 ==========

async function loadUsers() {
  const data = await fetchJSON(`${API_BASE}/users?days=30`);
  usersCache = Array.isArray(data) ? data : [];
  usersPage = 1;
  document.getElementById('users-search').value = '';
  renderUsersPage();
}

function filterUsers() { usersPage = 1; renderUsersPage(); }

function getFilteredUsers() {
  const q = document.getElementById('users-search').value.trim().toLowerCase();
  if (!q) return usersCache;
  return usersCache.filter(u => (u.user_id || '').toLowerCase().includes(q));
}

function renderUsersPage() {
  const filtered = getFilteredUsers();
  const total = filtered.length;
  const totalPages = Math.max(1, Math.ceil(total / USERS_PER_PAGE));
  if (usersPage > totalPages) usersPage = totalPages;
  const start = (usersPage - 1) * USERS_PER_PAGE;
  const pageData = filtered.slice(start, start + USERS_PER_PAGE);

  const tbody = document.getElementById('users-table');
  tbody.innerHTML = '';
  if (!total) {
    tbody.innerHTML = `<tr><td colspan="6">${emptyStateHTML('暂无用户数据', '当前时间范围内暂无活跃用户', '👥')}</td></tr>`;
    renderPagination(0, 0, 0);
    return;
  }
  pageData.forEach(u => {
    const tr = document.createElement('tr');
    const uid = u.user_id || '--';
    tr.innerHTML = `
      <td><span class="truncate-id font-mono text-xs text-gray-600" title="${uid}">${uid}</span></td>
      <td class="text-gray-500 text-xs">${(u.first_seen || '').slice(0, 10)}</td>
      <td class="text-gray-500 text-xs">${(u.last_seen || '').slice(0, 10)}</td>
      <td class="font-medium text-sm">${u.session_count}</td>
      <td>${u.avg_rating !== undefined && u.avg_rating !== null ? '⭐ ' + u.avg_rating.toFixed(1) : '<span class="text-gray-400">--</span>'}</td>
      <td><button class="text-blue-600 text-xs hover:underline" onclick="showUserDetail('${uid.replace(/'/g, "\\'")}')">详情</button></td>
    `;
    tbody.appendChild(tr);
  });
  renderPagination(usersPage, totalPages, total);
}

function renderPagination(current, total, count) {
  const container = document.getElementById('users-pagination');
  if (total <= 1) { container.innerHTML = `<span class="pagination-info">共 ${count} 条</span>`; return; }
  let html = '<div class="pagination">';
  html += `<button ${current === 1 ? 'disabled' : ''} onclick="goUsersPage(${current - 1})">上一页</button>`;
  const maxButtons = 5;
  let start = Math.max(1, current - Math.floor(maxButtons / 2));
  let end = Math.min(total, start + maxButtons - 1);
  if (end - start < maxButtons - 1) start = Math.max(1, end - maxButtons + 1);
  for (let i = start; i <= end; i++) html += `<button class="${i === current ? 'active' : ''}" onclick="goUsersPage(${i})">${i}</button>`;
  html += `<button ${current === total ? 'disabled' : ''} onclick="goUsersPage(${current + 1})">下一页</button>`;
  html += '</div>';
  html += `<span class="pagination-info">${(current - 1) * USERS_PER_PAGE + 1}-${Math.min(current * USERS_PER_PAGE, count)} / 共 ${count} 条</span>`;
  container.innerHTML = html;
}

function goUsersPage(p) { usersPage = p; renderUsersPage(); }

async function showUserDetail(userId) {
  const data = await fetchJSON(`${API_BASE}/users/${encodeURIComponent(userId)}`);
  const sessions = data.sessions || [];
  const html = sessions.length ? sessions.map(s => `
    <div class="py-2.5 border-b border-gray-100 text-sm">
      <div class="flex justify-between items-center">
        <span class="text-gray-600 font-mono text-xs">${s.session_id?.slice(0, 30) || ''}...</span>
        <span class="text-gray-400 text-xs">${(s.start_time || '').slice(0, 16)}</span>
      </div>
      <div class="flex gap-3 mt-1.5 items-center">
        <span class="text-xs bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">${s.turn_count || 0} 轮</span>
        <span class="text-xs text-gray-500">时长: <span class="font-medium">${s.duration_min || 0}min</span></span>
        <span class="text-xs text-gray-500">评分: <span class="font-medium">${s.rating || '--'}</span></span>
      </div>
    </div>
  `).join('') : '<p class="text-gray-400 text-sm py-4">无会话记录</p>';

  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.onclick = (e) => { if (e.target === e.currentTarget) modal.remove(); };
  modal.innerHTML = `
    <div class="modal-box" style="max-width:560px;" onclick="event.stopPropagation()">
      <div class="modal-header">
        <span class="font-semibold text-gray-800 text-sm">用户详情</span>
        <button onclick="this.closest('.modal-overlay').remove()" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
      </div>
      <div class="modal-body">
        <p class="text-xs text-gray-500 font-mono mb-3 break-all">${userId}</p>
        <div class="grid grid-cols-3 gap-3 mb-4 text-xs">
          <div class="bg-gray-50 rounded p-2"><div class="text-gray-500">总会话</div><div class="font-semibold text-gray-800 text-sm mt-0.5">${data.total_sessions || 0}</div></div>
          <div class="bg-gray-50 rounded p-2"><div class="text-gray-500">首次使用</div><div class="font-semibold text-gray-800 text-sm mt-0.5">${(data.first_seen || '').slice(0, 10) || '--'}</div></div>
          <div class="bg-gray-50 rounded p-2"><div class="text-gray-500">最后活跃</div><div class="font-semibold text-gray-800 text-sm mt-0.5">${(data.last_seen || '').slice(0, 10) || '--'}</div></div>
        </div>
        <div class="space-y-0">${html}</div>
      </div>
      <div class="modal-footer">
        <button onclick="this.closest('.modal-overlay').remove()" class="btn btn-primary btn-sm">关闭</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

// ========== 服务器健康监控 ==========

async function loadHealth() {
  const data = await fetchJSON(`${API_BASE}/health`);
  const status = data.status === 'healthy';

  document.getElementById('h-status').textContent = status ? '运行正常' : '异常';
  document.getElementById('h-status').className = status ? 'metric-value text-green-600' : 'metric-value text-red-600';
  document.getElementById('h-redis-clients').textContent = data.redis?.clients ?? '--';
  document.getElementById('h-redis-memory').textContent = data.redis?.used_memory_mb ? data.redis.used_memory_mb + ' MB' : '--';
  document.getElementById('h-redis-uptime').textContent = data.redis?.uptime_days ? data.redis.uptime_days + ' 天' : '--';
  document.getElementById('h-eval-records').textContent = data.evaluation?.records_30d ?? '--';
  document.getElementById('h-error').textContent = data.error || '无';
  document.getElementById('h-timestamp').textContent = data.timestamp ? data.timestamp.slice(0, 19).replace('T', ' ') : '--';
}

// ========== 留存分析 ==========

async function loadRetention() {
  const data = await fetchJSON(`${API_BASE}/retention?days=30`);
  const stats = data.daily_stats || [];

  if (!stats.length) {
    document.getElementById('retention-chart').innerHTML = emptyStateHTML('暂无留存数据', '需要更多用户会话数据', '📈');
    return;
  }

  // DAU 趋势图
  renderChart('retention-chart', {
    tooltip: { trigger: 'axis', axisPointer: { type: 'line' } },
    legend: { data: ['活跃用户', '新用户'], bottom: 0 },
    grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: { type: 'category', data: stats.map(s => s.date.slice(5)), axisLabel: { fontSize: 10, rotate: 45 } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '活跃用户', type: 'line', data: stats.map(s => s.active_users), smooth: true, itemStyle: { color: '#3b82f6' }, areaStyle: { color: 'rgba(59,130,246,0.1)' } },
      { name: '新用户', type: 'line', data: stats.map(s => s.new_users), smooth: true, itemStyle: { color: '#10b981' } },
    ]
  });

  // 统计卡片
  const totalActive = stats.reduce((a, s) => a + s.active_users, 0);
  const totalNew = stats.reduce((a, s) => a + s.new_users, 0);
  const avgDAU = stats.length ? Math.round(totalActive / stats.length) : 0;
  document.getElementById('r-avg-dau').textContent = avgDAU;
  document.getElementById('r-total-users').textContent = totalActive;
  document.getElementById('r-new-users').textContent = totalNew;
  document.getElementById('r-retention-d1').textContent = data.retention?.d1 !== null ? data.retention.d1 + '%' : '数据不足';
  document.getElementById('r-retention-d7').textContent = data.retention?.d7 !== null ? data.retention.d7 + '%' : '数据不足';
}

// ========== 图表工具 ==========

function renderChart(id, option, emptyHTML) {
  const el = document.getElementById(id);
  if (!el) return;
  if (emptyHTML) {
    if (chartInstances[id]) { chartInstances[id].dispose(); delete chartInstances[id]; }
    el.innerHTML = emptyHTML;
    return;
  }
  if (el.innerHTML && !chartInstances[id]) el.innerHTML = '';
  if (chartInstances[id]) chartInstances[id].dispose();
  chartInstances[id] = echarts.init(el);
  chartInstances[id].setOption(option);
}

window.addEventListener('resize', () => {
  Object.values(chartInstances).forEach(c => c && c.resize());
});

document.addEventListener('DOMContentLoaded', () => {
  checkAuth();
});
