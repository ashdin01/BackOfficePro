from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtCore import Qt


class KeyboardMixin:
    """
    Mixin that adds:
    - Escape: close/cancel
    - Ctrl+S: save (if self._save exists)
    - Enter on tables: open selected item
    """

    def setup_keyboard(self, table=None, on_enter=None, on_escape=None):
        # Escape — close
        escape_action = on_escape or self.close
        QShortcut(QKeySequence("Escape"), self, escape_action)

        # Ctrl+S — save
        if hasattr(self, '_save'):
            QShortcut(QKeySequence("Ctrl+S"), self, self._save)

        # Enter on table
        if table is not None:
            enter_action = on_enter or (self._edit if hasattr(self, '_edit') else None)
            if enter_action:
                orig_key_press = table.keyPressEvent
                def key_press(event, _enter=enter_action, _orig=orig_key_press):
                    if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                        _enter()
                    else:
                        _orig(event)
                table.keyPressEvent = key_press
