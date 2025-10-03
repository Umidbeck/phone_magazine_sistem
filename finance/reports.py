# finance/reports.py
from decimal import Decimal
from typing import Optional, Dict, Any
from django.db.models import Sum, Q
from django.apps import apps

from .models import Account, JournalLine

DEC0 = Decimal("0.00")


def _resolve_object_title(app_label: str, model_name: str, object_id: str) -> str:
    """
    Ledger qatorlaridagi object_app/object_model/object_id orqali asl obyektni topib,
    foydali nomini qaytaradi. Maydon nomlari turlicha bo‘lishi mumkinligi uchun
    dinamik tekshiruv ishlatamiz (name/title/number/code/...).
    """
    if not app_label or not model_name or not object_id:
        return ""
    try:
        Model = apps.get_model(app_label, model_name)
        if Model is None:
            return f"{app_label}.{model_name}#{object_id}"
        obj = Model.objects.filter(pk=object_id).first()
        if not obj:
            return f"{app_label}.{model_name}#{object_id}"

        # Ekran uchun sarlavha / nom — mavjud maydonlardan birini olamiz
        for attr in (
            "name", "title", "full_name", "username", "number", "code",
            "imei", "sku", "slug", "pk", "id"
        ):
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                return f"{app_label}.{model_name} — {val}"
        return f"{app_label}.{model_name}#{object_id}"
    except Exception:
        return f"{app_label}.{model_name}#{object_id}"


def _lines_grouped_by_object(account_code: str, date_from=None, date_to=None):
    """
    Berilgan hisob (account_code) bo‘yicha (app, model, id) kesimida yig‘indi.
    """
    acc = Account.objects.get(code=account_code)
    qs = JournalLine.objects.filter(account=acc)
    if date_from:
        qs = qs.filter(entry__date__gte=date_from)
    if date_to:
        qs = qs.filter(entry__date__lte=date_to)
    qs = qs.values("object_app", "object_model", "object_id").annotate(total=Sum("amount"))
    return list(qs)


def ar_breakdown(date_to=None, date_from=None):
    """
    AR (mijoz qarzlari) — object kesimida.
    """
    rows = _lines_grouped_by_object(Account.CODE_AR_CUSTOMERS, date_from, date_to)
    out = []
    for r in rows:
        total = r["total"] or DEC0
        if not total:
            continue
        out.append({
            "object": _resolve_object_title(r["object_app"], r["object_model"], r["object_id"]),
            "object_app": r["object_app"],
            "object_model": r["object_model"],
            "object_id": r["object_id"],
            "amount": total,
        })
    # AR odatda aktiv hisob, pozitiv qoldiqlarni ko‘rsatamiz
    out.sort(key=lambda x: x["amount"], reverse=True)
    return out


def ap_breakdown(date_to=None, date_from=None):
    """
    AP (ta’minotchiga qarzlar) — object kesimida.
    """
    rows = _lines_grouped_by_object(Account.CODE_AP_SUPPLIERS, date_from, date_to)
    out = []
    for r in rows:
        total = r["total"] or DEC0
        if not total:
            continue
        out.append({
            "object": _resolve_object_title(r["object_app"], r["object_model"], r["object_id"]),
            "object_app": r["object_app"],
            "object_model": r["object_model"],
            "object_id": r["object_id"],
            "amount": total,
        })
    out.sort(key=lambda x: x["amount"], reverse=True)
    return out


def commission_breakdown(date_from=None, date_to=None):
    """
    Komissiya analitikasi: ledgerdagi ikkala komissiya hisobidan:
      - Commission Expense (xarajat)  -> + (DR>0) sifatida
      - Commission Income  (daromad)  -> + (CR<0) manfiy yozuvni -1 ga ko‘paytiramiz
    Natija: object kesimida komissiya summalari (Expense/Income alohida)
    """
    exp_rows = _lines_grouped_by_object(Account.CODE_COMMISSION_EX, date_from, date_to)
    inc_rows = _lines_grouped_by_object(Account.CODE_COMMISSION_IN, date_from, date_to)

    out = {}

    def add_row(row, is_income=False):
        key = (row["object_app"], row["object_model"], row["object_id"])
        title = _resolve_object_title(*key)
        d = out.get(key) or {"object": title, "expense": DEC0, "income": DEC0}
        val = row["total"] or DEC0
        if is_income:
            # income hisobida kreditlar manfiy saqlangan bo‘lishi mumkin — musbat ko‘rsatamiz
            d["income"] += (val * Decimal("-1"))
        else:
            d["expense"] += val
        out[key] = d

    for r in exp_rows:
        add_row(r, is_income=False)
    for r in inc_rows:
        add_row(r, is_income=True)

    # chiqishni ro‘yxat ko‘rinishida va saralab beramiz
    res = []
    for (_a, _m, _i), d in out.items():
        d["net"] = (d["income"] - d["expense"])
        res.append(d)
    res.sort(key=lambda x: x["net"], reverse=True)
    return res
