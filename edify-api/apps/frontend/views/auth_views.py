from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib import messages
from apps.accounts.models import User, EdifyRole

def login_view(request):
    if request.user.is_authenticated:
        return redirect("/dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        remember_me = request.POST.get("remember_me") == "on"

        user = authenticate(request, username=email, password=password)
        if user is not None:
            if user.status != "active":
                return render(request, "pages/auth/login.html", {
                    "error": "Invalid email or password.",
                    "email": email
                })
            
            django_login(request, user)
            
            if not remember_me:
                request.session.set_expiry(0) # ends when browser closes
            else:
                request.session.set_expiry(1209600) # 2 weeks
                
            messages.success(request, f"Welcome back, {user.name}!")
            return redirect("/dashboard")
        else:
            return render(request, "pages/auth/login.html", {
                "error": "Invalid email or password.",
                "email": email
            })

    return render(request, "pages/auth/login.html")

@require_POST
def logout_view(request):
    django_logout(request)
    messages.success(request, "Logged out successfully.")
    return redirect("/login")

@login_required(login_url="/login")
@require_POST
def switch_role_view(request):
    role = request.POST.get("role")
    user = request.user
    if role in user.roles:
        user.active_role = role
        user.save()
        messages.success(request, f"Switched active role to {role}.")
    else:
        messages.error(request, "Access restricted: Invalid role request.")
    return redirect("/dashboard")
