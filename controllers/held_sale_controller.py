import models.held_sale as held_sale_model


def create_hold(terminal_id, operator, items, *, subtotal, gst_amount, total, note='') -> dict:
    return held_sale_model.create(terminal_id, operator, items,
                                   subtotal=subtotal, gst_amount=gst_amount,
                                   total=total, note=note)


def get_open_holds() -> list:
    return held_sale_model.get_open()


def get_hold(reference) -> dict | None:
    return held_sale_model.get_by_reference(reference)


def resume_hold(reference, resumed_by_terminal) -> dict:
    return held_sale_model.resume_atomic(reference, resumed_by_terminal)


def void_hold(reference) -> None:
    held_sale_model.void(reference)
