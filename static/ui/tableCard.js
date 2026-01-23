/* global window, document */
(function (global) {
  'use strict';

  /*
    Public API:
      TableCard.init({ gridId, totalTables })
      TableCard.updateGrid(masaData, opts)
      TableCard.build(index, masaData, opts)
      TableCard.countSerpme(siparisler)
      TableCard.getOpenMinutes(masaData, masa, tableSessions)
  */

  var gridId = null;
  var totalTables = 25;
  var nodeCache = {};
  var dataCache = {};
  var initDone = false;

  function countSerpme(siparisler) {
    var kisi = 0;
    (siparisler || []).forEach(function (order) {
      (order.items || []).forEach(function (item) {
        var name = String(item.name || '').toLowerCase();
        if (name.indexOf('serpme') !== -1) {
          kisi += Number(item.adet || 0);
        }
      });
    });
    return kisi;
  }

  function getOpenMinutes(masaData, masa, tableSessions) {
    var openTs = tableSessions && tableSessions[String(masa)];
    if (!openTs && masaData[masa]) {
      masaData[masa].siparisler.forEach(function (order) {
        if (order.masa_acilis_ts) {
          if (!openTs || order.masa_acilis_ts < openTs) {
            openTs = order.masa_acilis_ts;
          }
        }
      });
    }
    if (!openTs) return 0;
    var dt = new Date(openTs);
    if (Number.isNaN(dt.getTime())) return 0;
    return Math.max(1, Math.floor((Date.now() - dt.getTime()) / 60000));
  }

  function getGarsonName(data) {
    if (!data || !data.siparisler || !data.siparisler.length) return '';
    var last = data.siparisler[data.siparisler.length - 1];
    return last && last.garson ? String(last.garson) : '';
  }

  function build(index, masaData, opts) {
    var data = masaData[index];
    var totalText = data ? data.toplam + ' TL' : 'Bos';
    var kisi = data ? countSerpme(data.siparisler) : 0;
    var sure = data ? getOpenMinutes(masaData, index, opts.tableSessions) : 0;
    var div = document.createElement('div');
    var isMap = opts.isMap === true;
    div.className = (data ? 'table-card occupied' : 'table-card') + (isMap ? ' map-card' : '');
    div.dataset.masa = index;
    div.dataset.minutes = sure;
    if (typeof opts.onClick === 'function') {
      div.onclick = function () {
        opts.onClick(index);
      };
    }
    var rehberIcon = opts.rehberMasalar && opts.rehberMasalar[index] ? '*' : '';
    var billRequested = opts.billRequests && opts.billRequests[String(index)] && opts.billRequests[String(index)].value;
    var tableName = opts.tables && opts.tables[index] ? opts.tables[index] : 'Masa ' + index;
    var garsonName = data ? getGarsonName(data) : '';
    var nameText = tableName + (garsonName ? ' - ' + garsonName : '');
    var sureText = sure ? sure + ' dk' : '--';
    div.innerHTML = ''
      + '<div class="table-progress" aria-hidden="true"></div>'
      + (billRequested ? '<div class="bill-request-badge" title="Hesap istendi">\u2B50</div>' : '')
      + '<div class="table-name">' + nameText + (rehberIcon ? ' ' + rehberIcon : '') + '</div>'
      + '<div class="table-amount">' + totalText + '</div>'
      + '<div class="table-meta">'
      + '<span>&#x1F464; ' + kisi + ' kisi &#x23F1;&#xFE0F; ' + sureText + '</span>'
      + '</div>';
    return div;
  }

  function computeSnapshot(index, masaData, opts) {
    var data = masaData[index];
    var totalText = data ? data.toplam + ' TL' : 'Bos';
    var kisi = data ? countSerpme(data.siparisler) : 0;
    var sure = data ? getOpenMinutes(masaData, index, opts.tableSessions) : 0;
    var sureText = sure ? sure + ' dk' : '--';
    var rehberIcon = opts.rehberMasalar && opts.rehberMasalar[index] ? '*' : '';
    var billRequested = opts.billRequests && opts.billRequests[String(index)] && opts.billRequests[String(index)].value;
    var tableName = opts.tables && opts.tables[index] ? opts.tables[index] : 'Masa ' + index;
    var garsonName = data ? getGarsonName(data) : '';
    var nameText = tableName + (garsonName ? ' - ' + garsonName : '');
    return {
      occupied: !!data,
      totalText: totalText,
      kisi: kisi,
      sure: sure,
      sureText: sureText,
      tableName: nameText,
      rehberIcon: rehberIcon,
      billRequested: billRequested
    };
  }

  function ensureGrid(masaData, opts) {
    var grid = document.getElementById(gridId);
    if (!grid) return;
    if (!initDone) {
      grid.innerHTML = '';
      for (var i = 1; i <= totalTables; i++) {
        var node = build(i, masaData, opts);
        nodeCache[i] = node;
        grid.appendChild(node);
      }
      initDone = true;
    }
  }

  function updateNode(index, snapshot, opts) {
    var node = nodeCache[index];
    if (!node) return;
    var last = dataCache[index] || {};
    if (snapshot.occupied !== last.occupied) {
      if (snapshot.occupied) {
        node.classList.add('occupied');
      } else {
        node.classList.remove('occupied');
      }
    }
    if (snapshot.sure !== last.sure) {
      node.dataset.minutes = snapshot.sure;
    }
    var nameEl = node.querySelector('.table-name');
    var amountEl = node.querySelector('.table-amount');
    var metaEl = node.querySelector('.table-meta span');
    var nameText = snapshot.tableName + (snapshot.rehberIcon ? ' ' + snapshot.rehberIcon : '');
    var badge = node.querySelector('.bill-request-badge');
    if (snapshot.billRequested && !badge) {
      badge = document.createElement('div');
      badge.className = 'bill-request-badge';
      badge.textContent = '\u2B50';
      node.insertBefore(badge, node.firstChild.nextSibling);
    } else if (!snapshot.billRequested && badge) {
      badge.remove();
    }
    if (nameEl && nameText !== last.nameText) {
      nameEl.textContent = nameText;
    }
    if (amountEl && snapshot.totalText !== last.totalText) {
      amountEl.textContent = snapshot.totalText;
    }
    if (metaEl && (snapshot.kisi !== last.kisi || snapshot.sureText !== last.sureText)) {
      metaEl.innerHTML = '&#x1F464; ' + snapshot.kisi + ' kisi &#x23F1;&#xFE0F; ' + snapshot.sureText;
    }
    dataCache[index] = {
      occupied: snapshot.occupied,
      totalText: snapshot.totalText,
      kisi: snapshot.kisi,
      sure: snapshot.sure,
      sureText: snapshot.sureText,
      nameText: nameText,
      billRequested: snapshot.billRequested
    };
  }

  function updateGrid(masaData, opts) {
    if (!gridId) return;
    var safeOpts = opts || {};
    var data = masaData || {};
    ensureGrid(data, safeOpts);
    for (var i = 1; i <= totalTables; i++) {
      updateNode(i, computeSnapshot(i, data, safeOpts), safeOpts);
    }
  }

  function init(opts) {
    gridId = opts.gridId;
    totalTables = opts.totalTables || 25;
    if (global.APP && global.APP.on) {
      global.APP.on('tables:updated', function (payload) {
        var data = payload && payload.masaData ? payload.masaData : {};
        updateGrid(data, {
          totalTables: totalTables,
          isMap: false,
          tables: payload.tables || (global.APP.state && global.APP.state.tables),
          rehberMasalar: payload.rehberMasalar || (global.APP.state && global.APP.state.rehberMasalar),
          billRequests: payload.billRequests || (global.APP.state && global.APP.state.billRequests),
          tableSessions: payload.tableSessions || (global.APP.state && global.APP.state.tableSessions),
          onClick: payload.onClick || opts.onClick
        });
      });
    }
  }

  global.UI = global.UI || {};
  global.UI.TableCard = {
    init: init,
    build: build,
    updateGrid: updateGrid,
    countSerpme: countSerpme,
    getOpenMinutes: getOpenMinutes
  };
  global.TableCard = global.UI.TableCard;
})(window);
