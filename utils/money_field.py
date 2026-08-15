from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel


def money_field(spin_box) -> QWidget:
    """Wrap a QDoubleSpinBox with a '$' label placed outside the field
    instead of QDoubleSpinBox.setPrefix("$"), which embeds the symbol
    inside the editable text — forcing the cursor to land after it and
    getting in the way when a user selects-all and retypes an amount.

    Pass the returned widget to QFormLayout.addRow() in place of the
    spin box itself.
    """
    wrapper = QWidget()
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(QLabel("$"))
    row.addWidget(spin_box)
    return wrapper
