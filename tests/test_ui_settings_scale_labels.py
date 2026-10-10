from PyQt6.QtWidgets import QMessageBox

import controllers.settings_controller as settings_ctrl
from views.settings.settings_scale_labels import ScaleLabelsScreen


def test_preset_test_save_and_reload(qtbot, test_db, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    w = ScaleLabelsScreen()
    qtbot.addWidget(w)
    w.preset_cb.setCurrentIndex(w.preset_cb.findData('2 PPPPPP VVVVV C'))
    w.type_cb.setCurrentIndex(w.type_cb.findData('price'))
    w.test_edit.setText('2000140010004')
    assert 'PLU 140' in w.test_lbl.text() and '$10.00' in w.test_lbl.text()
    w._save()
    assert settings_ctrl.get_setting('scale_label_value_type') == 'price'
    w2 = ScaleLabelsScreen()
    qtbot.addWidget(w2)
    assert w2.preset_cb.currentData() == '2 PPPPPP VVVVV C'
    assert w2.type_cb.currentData() == 'price'
