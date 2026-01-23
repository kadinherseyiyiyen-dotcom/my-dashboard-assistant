/* global window, document */
(function (global) {
  'use strict';

  /*
    Public API:
      Timeline.updateLiveClock(clockId)
      Timeline.buildLabels({ innerId, pxPerMinute })
      Timeline.update({ innerId, pxPerMinute })
      Timeline.updateDensity({ label, score })
  */

  var analogRunning = false;
  function updateLiveClock(clockId) {
    var now = new Date();
    var clock = document.getElementById(clockId);
    if (!clock) return;
    if (clock.classList.contains('clock-face')) {
      startAnalogClock(clock);
      var digital = document.getElementById('clock-digital');
      if (digital) {
        digital.textContent = now.toLocaleTimeString('tr-TR');
      }
      return;
    }
    clock.textContent = now.toLocaleTimeString('tr-TR');
  }

  function startAnalogClock(clock) {
    if (analogRunning) return;
    analogRunning = true;
    var hourHand = clock.querySelector('[data-hand="hour"]');
    var minuteHand = clock.querySelector('[data-hand="minute"]');
    var secondHand = clock.querySelector('[data-hand="second"]');
    function tick() {
      var now = new Date();
      var ms = now.getMilliseconds();
      var seconds = now.getSeconds() + ms / 1000;
      var minutes = now.getMinutes() + seconds / 60;
      var hours = (now.getHours() % 12) + minutes / 60;
      if (hourHand) hourHand.style.transform = 'translate(-50%, -100%) rotate(' + (hours * 30) + 'deg)';
      if (minuteHand) minuteHand.style.transform = 'translate(-50%, -100%) rotate(' + (minutes * 6) + 'deg)';
      if (secondHand) secondHand.style.transform = 'translate(-50%, -100%) rotate(' + (seconds * 6) + 'deg)';
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function buildLabels(opts) {
    var inner = document.getElementById(opts.innerId);
    if (!inner) return;
    inner.innerHTML = '';
    var pxPerMinute = opts.pxPerMinute || 3;
    var totalWidth = 1440 * pxPerMinute;
    inner.style.width = totalWidth + 'px';
    for (var h = 0; h < 24; h++) {
      var full = document.createElement('span');
      full.className = 'timeline-tick hour';
      full.style.left = (h * 60 * pxPerMinute) + 'px';
      full.textContent = (h < 10 ? '0' + h : h) + ':00';
      inner.appendChild(full);

      var half = document.createElement('span');
      half.className = 'timeline-tick half';
      half.style.left = ((h * 60 + 30) * pxPerMinute) + 'px';
      half.textContent = (h < 10 ? '0' + h : h) + ':30';
      inner.appendChild(half);
    }
  }

  function update(opts) {
    var inner = document.getElementById(opts.innerId);
    if (!inner) return;
    var now = new Date();
    var minutes = (now.getHours() * 60) + now.getMinutes() + (now.getSeconds() / 60);
    var track = inner.parentElement;
    var trackWidth = track ? track.clientWidth : 0;
    var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var pxPerMinute = opts.pxPerMinute || 3;
    var centerX = trackWidth / 2;
    var translateX = centerX - (minutes * pxPerMinute);
    inner.style.transition = reduce ? 'none' : 'transform 0.6s linear';
    inner.style.transform = 'translate(' + translateX + 'px, -50%)';
  }

  function updateDensity(payload) {
    if (!payload) return;
    var densityText = document.getElementById(payload.densityTextId || 'density-text');
    var densityFill = document.getElementById(payload.densityFillId || 'density-fill');
    var densityScore = document.getElementById(payload.densityScoreId || 'density-score');
    var score = payload.score || 0;
    var label = payload.label || 'Normal';
    var config = payload.config || (global.CONFIG && global.CONFIG.density) || {};

    if (densityText) densityText.textContent = label;
    if (densityScore) densityScore.textContent = 'Skor: ' + score;
    if (densityFill) {
      densityFill.style.width = score + '%';
      densityFill.style.background = score >= (config.criticalThreshold || 100)
        ? '#ef4444'
        : (score >= (config.warnThreshold || 70)
          ? '#f59e0b'
          : (score < (config.lowThreshold || 50) ? '#3b82f6' : '#22c55e'));
    }
  }

  global.UI = global.UI || {};
  global.UI.Timeline = {
    updateLiveClock: updateLiveClock,
    buildLabels: buildLabels,
    update: update,
    updateDensity: updateDensity
  };
  global.Timeline = global.UI.Timeline;

  if (global.APP && global.APP.on) {
    global.APP.on('density:updated', function (payload) {
      updateDensity(payload);
    });
  }
})(window);
