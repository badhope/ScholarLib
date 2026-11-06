// Anti-flash theme bootstrap, loaded as an external file because the
// CSP script-src 'self' directive disallows inline scripts.
(function () {
  try {
    var stored = localStorage.getItem('theme');
    // 默认亮色：只在用户显式选择 dark，或显式选择 system 且系统偏好暗色时
    // 才进暗色。未设置过（首次访问）一律亮色——学术期刊的阅读预期是白纸黑字。
    var dark =
      stored === 'dark' ||
      (stored === 'system' &&
        window.matchMedia('(prefers-color-scheme: dark)').matches);
    if (dark) document.documentElement.classList.add('dark');
  } catch (e) {}
})();
