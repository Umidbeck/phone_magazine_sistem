from django.db.models import Q
from django.db.models.functions import Right

def digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def product_search_q(q: str) -> Q:
    q_norm = (q or "").strip()
    q_digits = digits_only(q_norm)

    if q_digits and len(q_digits) == 4 and q_digits == q_norm:
        # Indeksga mos: WHERE right(imei_full,4) ILIKE '1234'
        return Q(**{Right("imei_full", 4).resolve_expression(None).name: q_digits})
        # Django ORM’da bevosita Right(...) ni Q’da ishlatish noqulay,
        # shuning uchun view’da annotate qilib filter qilishni tavsiya etaman (quyida ko‘rsatilgan).

    # Boshqa hollarda: to‘liq IMEI (raqamlarni qiyoslaymiz) yoki brand/model
    q_im = digits_only(q_norm)
    filters = Q()
    if q_im:
        filters |= Q(imei_full__icontains=q_im)
    filters |= Q(brand__name__icontains=q_norm) | Q(model__name__icontains=q_norm)
    return filters
