/* 知眠官网流量埋点 (轻量版, ~70 行)
 * - 自动 PV (含 SPA pushState / hashchange)
 * - beforeunload + visibilitychange 上报停留时长
 * - localStorage visitor_id + sessionStorage session_id
 * - 不依赖任何第三方
 */
(function () {
  'use strict';
  if (window.__zmTracker) return;
  window.__zmTracker = true;

  var API = 'https://sleepai.chat';

  // visitor id (持久)
  var vid;
  try {
    vid = localStorage.getItem('zm_vid');
    if (!vid) {
      vid = 'v_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
      localStorage.setItem('zm_vid', vid);
    }
  } catch (e) {
    vid = 'v_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }

  // session id (per 浏览器 tab session)
  var sid;
  try {
    sid = sessionStorage.getItem('zm_sid');
    if (!sid) {
      sid = 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
      sessionStorage.setItem('zm_sid', sid);
    }
  } catch (e) {
    sid = 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 4);
  }

  var startTs = Date.now();
  var lastPage = '';

  function sendPV() {
    var page = location.pathname + location.search;
    if (page === lastPage) return;
    lastPage = page;
    try {
      fetch(API + '/api/v1/analytics/pv', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          visitor_id: vid,
          session_id: sid,
          page: page,
          ref: document.referrer || '',
        }),
        keepalive: true,
        credentials: 'omit',
      }).catch(function () {});
    } catch (e) {}
  }

  function sendEnd() {
    var duration = Math.floor((Date.now() - startTs) / 1000);
    var payload = JSON.stringify({ session_id: sid, duration_s: duration });
    try {
      if (navigator.sendBeacon) {
        var blob = new Blob([payload], { type: 'application/json' });
        navigator.sendBeacon(API + '/api/v1/analytics/end', blob);
      } else {
        fetch(API + '/api/v1/analytics/end', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
          keepalive: true,
          credentials: 'omit',
        }).catch(function () {});
      }
    } catch (e) {}
  }

  // 首次 PV
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sendPV);
  } else {
    sendPV();
  }

  // SPA 路由 hook
  var _push = history.pushState;
  history.pushState = function () {
    _push.apply(history, arguments);
    setTimeout(sendPV, 50);
  };
  var _replace = history.replaceState;
  history.replaceState = function () {
    _replace.apply(history, arguments);
    setTimeout(sendPV, 50);
  };
  window.addEventListener('popstate', function () { setTimeout(sendPV, 50); });
  window.addEventListener('hashchange', sendPV);

  // session 结束
  window.addEventListener('beforeunload', sendEnd);
  window.addEventListener('pagehide', sendEnd);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) sendEnd();
  });
})();
