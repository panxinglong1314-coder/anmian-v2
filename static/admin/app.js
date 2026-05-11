const API_BASE = '/api/v1/admin';
let adminToken = localStorage.getItem('admin_token') || '';
let refreshTimer = null;
let chartInstances = {};
let healthInterval = null;
let usersCache = [];
let usersPage = 1;
const USERS_PER_PAGE = 10;

// ========== Toast ==========
function toast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ'}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => { el.style.animation = 'toastOut .3s ease forwards'; setTimeout(() => el.remove(), 300); }, duration);
}

// ========== Modal ==========
function showModal(content, title = '详情') {
  const modal = document.getElementById('suggestion-modal');
  document.getElementById('suggestion-modal-body').textContent = content;
  document.querySelector('.modal-title').textContent = title;
  modal.classList.remove('hidden');
}
function hideModal() { document.getElementById('suggestion-modal').classList新增('hidden'); }
function closeModal(e) { if (e.target === e.currentTarget) hideModal(); }

// ========== Auth ==========
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
  const token = document.getElementById('login-input').value.trim();
  if (!token) return;
  try {
    const r = await fetch('/api/v1/admin/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
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
  } catch (e) { toast('登录失败: ' + e.message, 'error'); }
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

// ========== Health ==========
function startHealthCheck() {
  stopHealthCheck();
  checkHealth();
  healthInterval = setInterval(checkHealth, 60000);
}
function stopHealthCheck() { if (healthInterval) clearInterval(healthInterval); }

async function checkHealth() {
  const dot = document.getElementById('health-dot');
  const label = document.getElementById('health-label');
  if (!dot || !label) return;
  try {
    const r = await fetch('/api/v1/admin/health', { headers: { 'X-Admin-Token': adminToken } });
    const data = await r.json();
    const isHealthy = data.status === 'healthy';
    const issues = data.issues || [];
    dot.className = isHealthy ? 'dot dot-green' : 'dot dot-red';
    label.textContent = isHealthy ? '正常' : '异常(' + issues.length + '项)';
    if (!isHealthy && issues.length > 0) label.title = issues.join('; ');
  } catch (e) {
    dot.className = 'dot dot-red';
    label.textContent = '离线';
  }
}

// ========== Request ==========
async function fetchJSON(url) {
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (adminToken) headers['X-Admin-Token'] = adminToken;
    const r = await fetch(url, { headers });
    if (r.status === 401) { logout(); toast('认证已过期', 'error'); return { error: '未授权' }; }
    return await r.json();
  } catch (e) { toast('请求失败: ' + e.message, 'error'); return { error: e.message }; }
}

// ========== CSV ==========
async function downloadCSV(type) {
  const btnMap = { safety: 'btn-export-safety', evaluations: 'btn-export-quality', users: 'btn-export-users' };
  const btn = document.getElementById(btnMap[type]);
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 导出中...'; }
  const days = document.getElementById('export-days')?.value || 30;
  try {
    const headers = {};
    if (adminToken) headers['X-Admin-Token'] = adminToken;
    const r = await fetch(`${API_BASE}/export/${type}?days=${days}`, { headers });
    if (r.status === 401) { logout(); return; }
    const blob = await r.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${type}_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    toast('导出成功', 'success');
  } catch (e) { toast('导出失败: ' + e.message, 'error'); }
  finally { if (btn) { btn.disabled = false; btn.textContent = '📥 导出 CSV'; } }
}

// ========== Router ==========
const pageTitles = {
  dashboard: '仪表盘', safety: '安全中心', quality: 'AI 质量监控',
  users: '用户列表', health: '服务器监控', retention: '留存分析',
};

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  document.getElementById('page-' + name).classList.remove('hidden');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  const nav = document.querySelector(`[data-page="${name}"]`);
  if (nav) nav.classList.add('active');
  document.getElementById('page-title').textContent = pageTitles[name] || name;
  const loaders = { dashboard: loadDashboard, safety: loadSafety, quality: loadQuality,
                     users: loadUsers, health: loadHealth, retention: loadRetention };
  if (loaders[name]) loaders[name](loaders[name] === loadDashboard ? 7 : 30);
}

// ========== Auto Refresh ==========
function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(() => {
    const page = document.querySelector('.nav-item.active')?.dataset.page;
    if (page === 'dashboard') loadDashboard(7);
    if (page === 'safety') loadSafety();
    if (page === 'quality') loadQuality();
    if (page === 'users') loadUsers();
    if (page === 'health') loadHealth();
    if (page === 'retention') loadRetention();
  }, 300000);
}
function stopAutoRefresh() { if (refreshTimer) clearInterval(refreshTimer); }

// ========== Utils ==========
function emptyStateHTML(title, desc, icon = '📭') {
  return `<div class="empty-state"><div class="empty-state-icon">${icon}</div><div class="empty-state-title">${title}</div><div class="empty-state-desc">${desc}</div></div>`;
}

function trendBadge(delta) {
  if (delta === null || delta === undefined) return '<span class="text-gray-400 text-xs ml-1">--</span>';
  const sign = delta > 0 ? '+' : '';
  const cls = delta > 0 ? 'text-green-600' : delta < 0 ? 'text-red-500' : 'text-gray-400';
  const arrow = delta > 0 ? '↑' : delta < 0 ? '↓' : '→';
  return `<span class="${cls} text-xs font-medium ml-1">${arrow}${sign}${delta}%</span>`;
}

function setMetricCard(id, value, sub, barPercent, barColor) {
  document.getElementById(id).textContent = value;
  const subEl = document.getElementById(id + '-sub');
  if (subEl) subEl.innerHTML = sub;
  const bar = document.getElementById(id + '-bar');
  if (bar) { bar.style.width = Math.min(barPercent, 100) + '%'; if (barColor) bar.style.background = barColor; }
}

// ========== 仪表盘 ==========
async function loadDashboard(days) {
  const data = await fetchJSON(`${API_BASE}/dashboard?days=${days}`);
  const hasData = data && !data.error && !data.message;

  if (!hasData) {
    ['active-users', 'sessions', 'avg-turns', 'avg-duration', 'night-ratio', 'avg-rating'].forEach(id => {
      setMetricCard('d-' + id, '--', '暂无数据', 0, '#3b82f6');
    });
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    return;
  }

  const total = data.total_sessions || 0;
  const trend = data.trend || {};
  setMetricCard('d-active-users', data.active_users ?? 0,
    `共 ${total} 会话${trendBadge(trend.users_delta)}`, Math.min((data.active_users || 0) / Math.max(total, 1) * 100, 100), '#3b82f6');
  setMetricCard('d-sessions', total,
    `环比 ${trendBadge(trend.sessions_delta)}`, Math.min(total / 50 * 100, 100), '#8b5cf6');
  setMetricCard('d-avg-turns', data.avg_turns_per_session ?? 0,
    '每会话平均轮次', Math.min((data.avg_turns_per_session || 0) / 20 * 100, 100), '#10b981');
  // avg_duration: 从轮次估算（每轮约2分钟）
  const avgDur = data.avg_duration_min || 0;
  setMetricCard('d-avg-duration', avgDur > 0 ? avgDur + 'min' : '--',
    avgDur > 0 ? '每会话估算时长' : '暂无数据', Math.min(avgDur / 60 * 100, 100), '#6366f1');
  setMetricCard('d-night-ratio', (data.night_ratio ?? 0) + '%',
    '22:00-06:00', Math.min(data.night_ratio ?? 0, 100), '#f59e0b');
  const rating = data.user_rating_avg;
  setMetricCard('d-avg-rating', rating ?? '--',
    rating ? '满分 5.0' : '暂无评分', rating ? (rating / 5 * 100) : 0, '#ef4444');

  // 评级分布饼图
  const dist = data.rating_distribution || {};
  const totalRated = Object.values(dist).reduce((a, b) => a + b, 0);
  if (totalRated === 0) {
    renderChart('chart-rating-dist', null, emptyStateHTML('暂无评级数据', '当前时间范围内暂无会话评估记录', '📊'));
  } else {
    renderChart('chart-rating-dist', {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { bottom: 0, itemWidth: 10, itemHeight: 10, textStyle: { fontSize: 12 } },
      series: [{ type: 'pie', radius: ['40%', '65%'], center: ['50%', '45%'],
        label: { show: true, formatter: '{b}\n{c}', fontSize: 11 },
        data: [
          { value: dist['🟢优秀'] || 0, name: '优秀', itemStyle: { color: '#22c55e' } },
          { value: dist['🟡良好'] || 0, name: '良好', itemStyle: { color: '#eab308' } },
          { value: dist['🟠需改进'] || 0, name: '需改进', itemStyle: { color: '#f97316' } },
          { value: dist['🔴不合格'] || 0, name: '不合格', itemStyle: { color: '#ef4444' } },
        ] }]
    });
  }

  // 会话结局
  const outcomes = data.outcome_distribution || {};
  renderChart('chart-outcome', Object.keys(outcomes).length ? {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: Object.keys(outcomes), axisLabel: { fontSize: 11 } },
    yAxis: { type: 'value', minInterval: 1 },
    series: [{ type: 'bar', data: Object.values(outcomes), itemStyle: { color: '#3b82f6', borderRadius: [4, 4, 0, 0] }, barWidth: '50%' }]
  } : null, Object.keys(outcomes).length === 0 ? emptyStateHTML('暂无结局数据', '', '📈') : null);

  // 每日趋势图
  const daily = data.daily_trend || [];
  if (daily.length > 1) {
    renderChart('chart-daily-trend', {
      tooltip: { trigger: 'axis', axisPointer: { type: 'line' } },
      legend: { data: ['会话数', '活跃用户'], bottom: 0 },
      grid: { left: '3%', right: '4%', bottom: '15%', top: '10%', containLabel: true },
      xAxis: { type: 'category', data: daily.map(d => d.date.slice(5)), axisLabel: { fontSize: 9, rotate: 45 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [
        { name: '会话数', type: 'bar', data: daily.map(d => d.sessions), itemStyle: { color: '#8b5cf6' } },
        { name: '活跃用户', type: 'line', data: daily.map(d => d.active_users), smooth: true, itemStyle: { color: '#3b82f6' } },
      ]
    }, null);
  } else {
    renderChart('chart-daily-trend', null, emptyStateHTML('数据不足', '需要更多天的数据才能展示趋势', '📈'));
  }

  // 24小时时段热力图
  const hourly = data.hourly_distribution || [];
  if (hourly.length === 24) {
    const maxHourly = Math.max(...hourly, 1);
    renderChart('chart-hourly', {
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: Array.from({length: 24}, (_, i) => `${i}:00`), axisLabel: { fontSize: 9, rotate: 45 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{
        type: 'bar',
        data: hourly.map((v, h) => ({
          value: v,
          itemStyle: {
            color: h >= 22 || h < 6 ? `rgba(251,191,36,${Math.max(0.1, v / maxHourly)})` : `rgba(59,130,246,${Math.max(0.1, v / maxHourly)})`
          }
        })),
        barWidth: '50%',
      }]
    }, null);
  } else {
    renderChart('chart-hourly', null, emptyStateHTML('暂无时段数据', '', '🕐'));
  }

  document.getElementById('last-update').textContent = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

// ========== 安全中心 ==========
async function loadSafety() {
  const data = await fetchJSON(`${API_BASE}/safety?days=30`);
  const events = Array.isArray(data) ? data : [];

  const total = events.length;
  const crisis = events.filter(e => e.crisis_status === '已识别').length;
  const bad = events.filter(e => e.bad_advice_found).length;
  // safety_pass: 直接从事件数据中统计
  const safe = events.filter(e => e.safety_pass === true).length;

  document.getElementById('s-total').textContent = total;
  document.getElementById('s-missed').textContent = crisis;
  document.getElementById('s-bad').textContent = bad;
  document.getElementById('s-pass').textContent = safe;

  const tbody = document.getElementById('safety-table');
  tbody.innerHTML = '';
  if (!events.length) {
    tbody.innerHTML = `<tr><td colspan="7">${emptyStateHTML('暂无安全事件', '最近30天未检测到危机或不当建议', '🛡️')}</td></tr>`;
    return;
  }
  events.forEach(e => {
    const severity = e.severity || '正常';
    const sevCls = severity === '危险' ? 'badge-red' : severity === '警告' ? 'badge-orange' : 'badge-gray';
    const crisisCls = e.crisis_status === '已识别' ? 'badge-yellow' : 'badge-green';
    const suggestion = (e.top_suggestion || '暂无').replace(/"/g, '&quot;').replace(/'/g, "\\'");
    const row = document.createElement('tr');
    row.innerHTML = `
      <td class="text-gray-500 text-xs">${(e.timestamp || '').slice(0, 16)}</td>
      <td><span class="truncate-id font-mono text-xs text-gray-500">${e.user_id || '--'}</span></td>
      <td><span class="badge ${sevCls}">${severity}</span></td>
      <td><span class="badge ${crisisCls}">${e.crisis_status || '正常'}</span></td>
      <td>${e.bad_advice_found ? '<span class="badge badge-red">是</span>' : '<span class="badge badge-green">否</span>'}</td>
      <td class="text-xs">${e.empathy !== undefined ? `共${e.empathy}/5` : '--'} / ${e.tech !== undefined ? `技${e.tech}/9` : ''}</td>
      <td><button class="text-blue-600 text-xs hover:underline" onclick="showModal('${suggestion}', '处理建议')">查看建议</button></td>
    `;
    tbody.appendChild(row);
  });
}

// ========== AI 质量 ==========
async function loadQuality() {
  const data = await fetchJSON(`${API_BASE}/quality?days=30`);
  const hasData = data && !data.error && !data.message;

  if (!hasData) {
    ['q-empathy', 'q-tech', 'q-coherence'].forEach(id => setMetricCard(id, '--', '暂无数据', 0, '#3b82f6'));
    ['chart-empathy-dist', 'chart-tech-dist'].forEach(id => renderChart(id, null, emptyStateHTML('暂无数据', '', '📊')));
    document.getElementById('quality-failures').innerHTML = emptyStateHTML('数据积累中', '预计 10 条会话后展示高频失败模式', '🔧');
    return;
  }

  const emp = data.empathy?.mean, tech = data.technical?.mean, coh = data.coherence?.mean;
  setMetricCard('q-empathy', emp?.toFixed(1) ?? '--', `共情 · ${emp}/5`, Math.min((emp || 0) / 5 * 100, 100), '#8b5cf6');
  setMetricCard('q-tech', tech?.toFixed(1) ?? '--', `技术 · ${tech}/9`, Math.min((tech || 0) / 9 * 100, 100), '#06b6d4');
  setMetricCard('q-coherence', coh?.toFixed(1) ?? '--', `连贯 · ${coh}/5`, Math.min((coh || 0) / 5 * 100, 100), '#10b981');

  // 共情分布
  const empDist = data.empathy?.distribution || {};
  const empTotal = Object.values(empDist).reduce((a, b) => a + b, 0);
  if (empTotal === 0) {
    renderChart('chart-empathy-dist', null, emptyStateHTML('暂无数据', '', '📊'));
  } else {
    renderChart('chart-empathy-dist', {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: ['0','1','2','3','4','5'], axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', data: [0,1,2,3,4,5].map(i => empDist[String(i)] || 0), itemStyle: { color: '#8b5cf6', borderRadius: [4,4,0,0] }, barWidth: '50%' }]
    });
  }

  // 技术分布
  const techDist = data.technical?.distribution || {};
  const techTotal = Object.values(techDist).reduce((a, b) => a + b, 0);
  if (techTotal === 0) {
    renderChart('chart-tech-dist', null, emptyStateHTML('暂无数据', '', '📊'));
  } else {
    renderChart('chart-tech-dist', {
      tooltip: { trigger: 'axis' },
      grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
      xAxis: { type: 'category', data: ['0','1','2','3','4','5','6','7','8','9'], axisLabel: { fontSize: 11 } },
      yAxis: { type: 'value', minInterval: 1 },
      series: [{ type: 'bar', data: [0,1,2,3,4,5,6,7,8,9].map(i => techDist[String(i)] || 0), itemStyle: { color: '#06b6d4', borderRadius: [4,4,0,0] }, barWidth: '50%' }]
    });
  }

  // 失败模式（带改进建议）
  const failures = data.top_failure_modes || [];
  const fDiv = document.getElementById('quality-failures');
  if (!failures.length) {
    fDiv.innerHTML = emptyStateHTML('数据积累中', '预计 10 条会话后展示高频失败模式', '🔧');
    return;
  }
  fDiv.innerHTML = failures.map((f, i) => `
    <div class="p-3 border-b border-gray-100 last:border-0">
      <div class="flex items-start justify-between gap-2">
        <div class="flex items-start gap-2 flex-1">
          <span class="flex-shrink-0 w-5 h-5 rounded bg-red-100 text-red-600 text-xs flex items-center justify-center font-bold mt-0.5">${i + 1}</span>
          <div>
            <div class="text-sm font-medium text-gray-800">${f.issue}</div>
            <div class="text-xs text-gray-500 mt-0.5">出现次数: <span class="font-medium">${f.count}</span> 次</div>
          </div>
        </div>
        <button onclick="showModal('${(f.suggestion || '建议人工复核').replace(/'/g, "\\'")}', '改进建议: ${f.issue}')"
          class="flex-shrink-0 text-blue-600 text-xs hover:underline">改进建议 →</button>
      </div>
    </div>
  `).join('');
}

// ========== 用户管理 ==========
async function deleteUser(userId) {
  if (!confirm('确定删除用户 ' + userId + '？此操作不可恢复！')) return;
  try {
    const r = await fetch(`${API_BASE}/users/${encodeURIComponent(userId)}/delete`, {
      method: 'DELETE',
      headers: { 'X-Admin-Token': adminToken }
    });
    const data = await r.json();
    if (data.success) {
      toast('已删除: ' + userId, 'success');
      loadUsers();
    } else {
      toast('删除失败: ' + (data.error || '未知错误'), 'error');
    }
  } catch (e) { toast('请求失败: ' + e.message, 'error'); }
}

async function toggleUser(userId, action) {
  if (!confirm('确定' + (action === 'disable' ? '禁用' : '启用') + '用户 ' + userId + '？')) return;
  try {
    const r = await fetch(`${API_BASE}/users/${encodeURIComponent(userId)}/toggle?action=${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Admin-Token': adminToken }
    });
    const data = await r.json();
    if (data.success) {
      toast((action === 'disable' ? '已禁用' : '已启用') + ': ' + userId, 'success');
      loadUsers();
    } else {
      toast('操作失败: ' + (data.error || '未知错误'), 'error');
    }
  } catch (e) { toast('请求失败: ' + e.message, 'error'); }
}

async function loadUsers() {
  const data = await fetchJSON(`${API_BASE}/users?days=30`);
  usersCache = Array.isArray(data) ? data : [];
  usersPage = 1;
  if (document.getElementById('users-search')) document.getElementById('users-search').value = '';
  renderUsersPage();
}

function getFilteredUsers() {
  const q = (document.getElementById('users-search')?.value || '').trim().toLowerCase();
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
    tbody.innerHTML = `<tr><td colspan="6">${emptyStateHTML('暂无用户', '', '👥')}</td></tr>`;
    renderPagination(0, 0, 0);
    return;
  }
  pageData.forEach(u => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><span class="truncate-id font-mono text-xs text-gray-600">${u.user_id || '--'}</span></td>
      <td class="text-gray-500 text-xs">${(u.first_seen || '').slice(0, 10)}</td>
      <td class="text-gray-500 text-xs">${(u.last_seen || '').slice(0, 10)}</td>
      <td class="font-medium text-sm">${u.session_count || 0}</td>
      <td>${u.total_turns ? `<span class="text-xs text-gray-500">${u.total_turns}轮</span>` : '--'}</td>
      <td>${u.avg_rating ? '<span class="text-yellow-500 text-xs">★ ' + u.avg_rating + '</span>' : '<span class="text-gray-300 text-xs">--</span>'}</td>
      <td>${u.subscription_plan ? (u.subscription_plan === "free" ? '<span class="text-gray-400 text-xs">免费</span>' : '<span class="text-blue-500 text-xs">' + u.subscription_plan + '</span>') : '<span class="text-gray-300 text-xs">--</span>'}</td>
      <td>
        <button class="text-red-500 text-xs hover:underline mr-1" onclick="deleteUser('${(u.user_id || '').replace(/'/g, "\'")}')">删除</button>
        <button class="text-orange-500 text-xs hover:underline mr-1" onclick="toggleUser('${(u.user_id || '').replace(/'/g, "\'")}', 'disable')">禁用</button>
        <button class="text-green-600 text-xs hover:underline mr-1" onclick="toggleUser('${(u.user_id || '').replace(/'/g, "\'")}', 'enable')">启用</button>
        <button class="text-blue-600 text-xs hover:underline" onclick="showUserDetail('${(u.user_id || '').replace(/'/g, "\'")}')">详情</button>
      </td>

    `;
    tbody.appendChild(row);
  });
  renderPagination(usersPage, totalPages, total);
}

function renderPagination(current, total, count) {
  const container = document.getElementById('users-pagination');
  if (total <= 1) { container.innerHTML = `<span class="pagination-info">共 ${count} 条</span>`; return; }
  let html = '<div class="pagination">';
  html += `<button ${current === 1 ? 'disabled' : ''} onclick="goUsersPage(${current - 1})">上一页</button>`;
  for (let i = 1; i <= total; i++) html += `<button class="${i === current ? 'active' : ''}" onclick="goUsersPage(${i})">${i}</button>`;
  html += `<button ${current === total ? 'disabled' : ''} onclick="goUsersPage(${current + 1})">下一页</button>`;
  html += '</div>';
  html += `<span class="pagination-info">${start = (current-1)*USERS_PER_PAGE+1}-${Math.min(current*USERS_PER_PAGE,count)} / 共 ${count} 条</span>`;
  container.innerHTML = html;
}

function goUsersPage(p) { usersPage = p; renderUsersPage(); }

async function showUserDetail(userId) {
  const data = await fetchJSON(`${API_BASE}/users/${encodeURIComponent(userId)}`);
  const sessions = data.sessions || [];
  const html = sessions.length ? sessions.map(s => `
    <div class="py-2.5 border-b border-gray-100 text-sm">
      <div class="flex justify-between items-center">
        <span class="text-gray-400 text-xs font-mono">${s.session_id?.slice(0, 35) || ''}</span>
        <span class="text-gray-400 text-xs">${(s.start_time || '').slice(0, 16)}</span>
      </div>
      ${s.user_preview ? `<div class="mt-1 text-xs text-gray-600 bg-gray-50 rounded px-2 py-1 truncate">👤 ${s.user_preview}</div>` : ''}
      <div class="flex gap-3 mt-1.5 items-center">
        <span class="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded">${s.turn_count || 0} 轮</span>
        <span class="text-xs text-gray-500">估算时长: <span class="font-medium">${s.duration_min || 0}min</span></span>
      </div>
    </div>
  `).join('') : '<p class="text-gray-400 text-sm py-4 text-center">无会话记录</p>';

  const modal = document.createElement('div');
  modal.className = 'modal-overlay';
  modal.onclick = (e) => { if (e.target === e.currentTarget) modal.remove(); };
  modal.innerHTML = `
    <div class="modal-box" style="max-width:600px;max-height:80vh;display:flex;flex-direction:column" onclick="event.stopPropagation()">
      <div class="modal-header">
        <span class="font-semibold text-gray-800 text-sm">用户详情</span>
        <button onclick="this.closest('.modal-overlay').remove()" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
      </div>
      <div class="modal-body overflow-auto flex-1">
        <p class="text-xs text-gray-400 font-mono mb-3 break-all">${userId}</p>
        <div class="grid grid-cols-3 gap-2 mb-3">
          <div class="bg-gray-50 rounded p-2 text-center"><div class="text-gray-500 text-xs">总会话</div><div class="font-bold text-gray-800 text-sm mt-0.5">${data.total_sessions || 0}</div></div>
          <div class="bg-gray-50 rounded p-2 text-center"><div class="text-gray-500 text-xs">首次使用</div><div class="font-bold text-gray-800 text-sm mt-0.5">${(data.first_seen || '').slice(0, 10) || '--'}</div></div>
          <div class="bg-gray-50 rounded p-2 text-center"><div class="text-gray-500 text-xs">最后活跃</div><div class="font-bold text-gray-800 text-sm mt-0.5">${(data.last_seen || '').slice(0, 10) || '--'}</div></div>
        </div>
        <div class="text-xs text-gray-500 mb-2">会话列表（最近${sessions.length}条）</div>
        <div class="space-y-0">${html}</div>
      </div>
      <div class="modal-footer"><button onclick="this.closest('.modal-overlay').remove()" class="btn btn-primary btn-sm">关闭</button></div>
    </div>
  `;
  document.body.appendChild(modal);
}

// ========== 服务器健康 ==========
async function loadHealth() {
  const data = await fetchJSON(`${API_BASE}/health`);
  const ok = data.status === 'healthy';
  document.getElementById('h-status').textContent = ok ? '运行正常' : '异常';
  document.getElementById('h-status').className = ok ? 'metric-value text-green-600' : 'metric-value text-red-600';
  document.getElementById('h-redis-clients').textContent = data.redis?.clients ?? '--';
  document.getElementById('h-redis-memory').textContent = data.redis?.used_memory_mb ? data.redis.used_memory_mb + ' MB' : '--';
  document.getElementById('h-redis-uptime').textContent = data.redis?.uptime_days ? data.redis.uptime_days + ' 天' : '--';
  document.getElementById('h-redis-keys').textContent = data.redis?.total_keys ?? '--';
  document.getElementById('h-eval-records').textContent = data.evaluation?.records_30d ?? '--';
  document.getElementById('h-total-req').textContent = data.api_stats?.total_requests ?? '--';
  document.getElementById('h-avg-rt').textContent = data.api_stats?.avg_response_ms ? data.api_stats.avg_response_ms + ' ms' : '--';
  document.getElementById('h-p95-rt').textContent = data.api_stats?.p95_response_ms ? data.api_stats.p95_response_ms + ' ms' : '--';
  // Issues list
  const issuesEl = document.getElementById('h-issues-list');
  if (issuesEl) {
    const issues = data.issues || [];
    if (issues.length === 0) {
      issuesEl.innerHTML = '<p class="text-green-600">✓ 全部正常</p>';
    } else {
      issuesEl.innerHTML = issues.map(i => '<p class="text-red-500">✗ ' + i + '</p>').join('');
    }
  }
  // System metrics
  const sys = data.system || {};
  document.getElementById('h-sys-load').textContent = sys.load_ratio ? sys.load_ratio.toFixed(2) + ' (核心比)' : '--';
  const memUsed = sys.memory_used_mb; const memTot = sys.memory_total_mb;
  document.getElementById('h-sys-mem').textContent = (memUsed && memTot) ? memUsed + '/' + memTot + ' MB' : '--';
  document.getElementById('h-error').textContent = (data.issues && data.issues.length > 0) ? data.issues[0] : '无';
  document.getElementById('h-timestamp').textContent = data.timestamp ? data.timestamp.slice(0, 19).replace('T', ' ') : '--';

  // Render health time-series chart
  try {
    const hist = await fetchJSON(API_BASE + '/health/history?hours=24');
    renderHealthChart(hist);
  } catch(e) { console.error('health chart error:', e); }
}

function renderHealthChart(data) {
  const el = document.getElementById('health-chart');
  if (!el) return;
  if (!data || data.length < 2) {
    el.innerHTML = '<div class="text-center text-gray-400 text-xs pt-8">数据不足（需要至少2个数据点）</div>';
    return;
  }
  const times = data.map(d => d.ts ? d.ts.slice(11, 16) : '').reverse();
  const clients = data.map(d => d.clients || 0).reverse();
  const loads = data.map(d => d.load || 0).reverse();
  const redisMem = data.map(d => d.mem_mb || 0).reverse();
  const sysMem = data.map(d => d.sys_mem_mb || 0).reverse();

  const option = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'line' } },
    legend: { data: ['Redis连接', 'CPU负载', 'Redis内存MB'], bottom: 0, textStyle: { fontSize: 10 } },
    grid: { left: '3%', right: '4%', bottom: '20%', top: '8%', containLabel: true },
    xAxis: { type: 'category', data: times, axisLabel: { fontSize: 9, rotate: 30 } },
    yAxis: [
      { type: 'value', name: '连接/负载', axisLabel: { fontSize: 9 }, splitLine: { lineStyle: { opacity: 0.2 } } },
      { type: 'value', name: '内存MB', axisLabel: { fontSize: 9 }, splitLine: { show: false } }
    ],
    series: [
      { name: 'Redis连接', type: 'line', data: clients, smooth: true, itemStyle: { color: '#3b82f6' }, yAxisIndex: 0 },
      { name: 'CPU负载', type: 'line', data: loads, smooth: true, itemStyle: { color: '#f97316' }, yAxisIndex: 0 },
      { name: 'Redis内存MB', type: 'line', data: redisMem, smooth: true, itemStyle: { color: '#a855f7' }, yAxisIndex: 1 },
    ]
  };

  if (window._healthChart) { window._healthChart.dispose(); }
  window._healthChart = echarts.init(el);
  window._healthChart.setOption(option);
}

// ========== 留存分析 ==========
async function loadRetention() {
  const data = await fetchJSON(`${API_BASE}/retention?days=30`);
  const stats = data.daily_stats || [];
  if (!stats.length) {
    document.getElementById('retention-chart').innerHTML = emptyStateHTML('暂无留存数据', '', '📈');
    return;
  }
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
  }, null);

  const totalActive = stats.reduce((a, s) => a + s.active_users, 0);
  const totalNew = stats.reduce((a, s) => a + s.new_users, 0);
  const avgDAU = stats.length ? Math.round(totalActive / stats.length) : 0;
  document.getElementById('r-avg-dau').textContent = avgDAU;
  document.getElementById('r-total-users').textContent = totalActive;
  document.getElementById('r-new-users').textContent = totalNew;
  document.getElementById('r-retention-d1').textContent = data.retention?.d1 !== null ? data.retention.d1 + '%' : '数据不足';
  document.getElementById('r-retention-d7').textContent = data.retention?.d7 !== null ? data.retention.d7 + '%' : '数据不足';
}

// ========== Charts ==========
function renderChart(id, option, emptyHTML) {
  const el = document.getElementById(id);
  if (!el) return;
  if (emptyHTML) { if (chartInstances[id]) { chartInstances[id].dispose(); delete chartInstances[id]; } el.innerHTML = emptyHTML; return; }
  if (chartInstances[id]) chartInstances[id].dispose();
  chartInstances[id] = echarts.init(el);
  chartInstances[id].setOption(option);
}

window.addEventListener('resize', () => Object.values(chartInstances).forEach(c => c?.resize()));
document.addEventListener('DOMContentLoaded', checkAuth);
