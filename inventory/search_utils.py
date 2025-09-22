# inventory/search_utils.py
from django.db.models import Q
from django.db.models.functions import Length, Substr
from inventory.models import Product

def digits_only(s: str) -> str:
    # Unicode raqamlar ham tozalanadi (masalan, arab raqamlari)
    return "".join(ch for ch in (s or "") if ch.isdigit())

def scope_products_by_user(user, qs):
    """
    Owner: hamma do'konlar.
    Seller: faqat o'z do'koni.
    Agar seller.store_id = None bo'lsa, dev rejimida hammasini ko'rsatamiz (diagnostika oson bo'lsin).
    Xavfsizlikni prod rejimda qat'iylashtirasiz.
    """
    if getattr(user, "is_owner", False):
        return qs
    # Seller
    if getattr(user, "store_id", None):
        return qs.filter(store_id=user.store_id)
    # Sellerga store biriktirilmagan bo'lsa — diagnostika uchun cheklamaysiz (xohlasangiz .none() qiling)
    return qs

def product_search_queryset(
    user,
    q: str,
    base_qs=None,
    *,
    for_sale: bool = False,
    include_archived: bool = False,
    store_id: int | None = None,
):
    """
    Qidiruv qoidalari:
      - 4 raqam kiritilsa => oxirgi 4 bo'yicha: imei_last4, substr fallback, endswith fallback.
      - Aks holda => full IMEI (raqamlar bo'yicha), brand, model.
      - Owner bo'lsa istalgan do'kon; GET ?store=... bilan toraytirish mumkin.
      - Seller bo'lsa o'z do'koni (yoki store_id None bo'lsa diagnostika uchun cheklamaysiz).
      - include_archived=False bo'lsa arxivlar yashiriladi.
      - for_sale=True bo'lsa faqat available.
    """
    qs = base_qs or Product.objects.select_related("brand", "model", "store")

    # Scope
    qs = scope_products_by_user(user, qs)
    if getattr(user, "is_owner", False) and store_id:
        qs = qs.filter(store_id=store_id)

    # Archived
    if not include_archived:
        qs = qs.filter(is_archived=False)

    # Status
    if for_sale:
        qs = qs.filter(status="available")

    # Query
    q = (q or "").strip()
    if not q:
        return qs

    q_digits = digits_only(q)
    text_cond = Q(brand__name__icontains=q) | Q(model__name__icontains=q)

    if len(q_digits) == 4:
        # Legacy yozuvlar uchun fallback: substr bilan oxirgi 4 ni ajratamiz
        qs = qs.annotate(last4=Substr("imei_full", Length("imei_full") - 3, 4))
        cond = (
            Q(imei_last4=q_digits)        # agar ustun bor va to'ldirilgan bo'lsa — tez
            | Q(last4=q_digits)           # fallback: substr
            | Q(imei_full__endswith=q_digits)  # yana fallback
        )
        return qs.filter(cond | text_cond)

    # 5+ raqam (yoki aralash) bo'lsa — IMEI ichidan raqamlari bo'yicha
    if q_digits:
        return qs.filter(Q(imei_full__icontains=q_digits) | text_cond)

    # Faqat matn bo'lsa — brand/model
    return qs.filter(text_cond)
