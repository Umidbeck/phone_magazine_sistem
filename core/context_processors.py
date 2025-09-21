def i18n_flags(request):
    return {
        "lang_code": getattr(getattr(request, "LANGUAGE_CODE", None), "lower", lambda: "")() or request.LANGUAGE_CODE
    }
