from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib import messages
from django.utils.translation import gettext as _
from .models import Brand, ModelName, Color
from .forms import BrandForm, ModelNameForm, ColorForm

def owner_required(view):
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_owner:
            return HttpResponseForbidden(_("Only owner can manage reference data."))
        return view(request, *args, **kwargs)
    return _wrapped

@owner_required
def brand_list(request):
    qs = Brand.objects.order_by("name")
    return render(request, "reference/brand_list.html", {"items": qs})

@owner_required
def brand_form(request, pk=None):
    obj = get_object_or_404(Brand, pk=pk) if pk else None
    form = BrandForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Brand saved."))
        return redirect("brand_list")
    return render(request, "reference/brand_form.html", {"form": form, "obj": obj})

@owner_required
def model_list(request):
    qs = ModelName.objects.select_related("brand").order_by("brand__name","name")
    return render(request, "reference/model_list.html", {"items": qs})

@owner_required
def model_form(request, pk=None):
    obj = get_object_or_404(ModelName, pk=pk) if pk else None
    form = ModelNameForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Model saved."))
        return redirect("model_list")
    return render(request, "reference/model_form.html", {"form": form, "obj": obj})

@owner_required
def color_list(request):
    qs = Color.objects.order_by("name")
    return render(request, "reference/color_list.html", {"items": qs})

@owner_required
def color_form(request, pk=None):
    obj = get_object_or_404(Color, pk=pk) if pk else None
    form = ColorForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Color saved."))
        return redirect("color_list")
    return render(request, "reference/color_form.html", {"form": form, "obj": obj})

# --------- Dependent select (Ajax JSON) ----------
@login_required
def models_by_brand_json(request, brand_id):
    # Seller ham foydalanadi (yangi product formasi)
    items = ModelName.objects.filter(brand_id=brand_id, is_active=True)\
            .order_by("name").values("id","name")
    return JsonResponse({"results": list(items)})
