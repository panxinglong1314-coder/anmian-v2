// Diagnostic first: load echarts synchronously
(function() {
  var script = document.createElement('script');
  script.src = '/admin/echarts.min.js?v=121145';
  script.onload = function() {
    document.getElementById('result').innerHTML = '<span style="color:green">✅ ECharts ' + echarts.version + ' 加载成功！版本：' + echarts.version + '</span>';
    // Test it
    var chart = echarts.init(document.createElement('div'));
    document.getElementById('result').innerHTML += '<br><span style="color:green">✅ Chart instance created: ' + !!chart + '</span>';
  };
  script.onerror = function(e) {
    document.getElementById('result').innerHTML = '<span style="color:red">❌ 加载失败: ' + (e.message || '未知错误') + '</span><pre>' + (script.src || '') + '</pre>';
  };
  document.head.appendChild(script);
})();