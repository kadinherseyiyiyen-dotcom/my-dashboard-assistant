/* global window, document */
(function (global) {
  'use strict';

  /*
    Public API:
      Modal.open(id)
      Modal.close(id)
  */

  function open(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'block';
  }

  function close(id) {
    var el = document.getElementById(id);
    if (el) el.style.display = 'none';
  }

  global.UI = global.UI || {};
  global.UI.Modal = {
    open: open,
    close: close
  };
  global.Modal = global.UI.Modal;
})(window);
