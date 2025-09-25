# inventory/mixins.py
def can_edit_product(user, product) -> bool:
    if getattr(user, "is_owner", False):
        return True
    return getattr(product, "created_by_id", None) == getattr(user, "id", None)
