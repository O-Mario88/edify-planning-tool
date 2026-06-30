import re

shell_content = """{% extends "base.html" %}

{% block content %}
<div 
  x-data="{ sidebarOpen: false, userMenuOpen: false }" 
  class="h-full flex overflow-hidden bg-[var(--bg-page)]"
>
  <!-- Off-canvas mobile menu -->
  <div 
    x-show="sidebarOpen" 
    class="md:hidden fixed inset-0 flex z-40" 
    style="display: none;"
    role="dialog" 
    aria-modal="true"
  >
    <div 
      x-show="sidebarOpen" 
      x-transition:enter="transition-opacity ease-linear duration-300"
      x-transition:enter-start="opacity-0"
      x-transition:enter-end="opacity-100"
      x-transition:leave="transition-opacity ease-linear duration-300"
      x-transition:leave-start="opacity-100"
      x-transition:leave-end="opacity-0"
      class="fixed inset-0 bg-slate-600/75" 
      @click="sidebarOpen = false"
      aria-hidden="true"
    ></div>

    <div 
      x-show="sidebarOpen"
      x-transition:enter="transition ease-in-out duration-300 transform"
      x-transition:enter-start="-translate-x-full"
      x-transition:enter-end="translate-x-0"
      x-transition:leave="transition ease-in-out duration-300 transform"
      x-transition:leave-start="translate-x-0"
      x-transition:leave-end="-translate-x-full"
      class="relative flex-1 flex flex-col max-w-xs w-full bg-[#304654]"
    >
      <div class="absolute top-0 right-0 -mr-12 pt-2">
        <button 
          type="button" 
          class="ml-1 flex items-center justify-center h-10 w-10 rounded-full focus:outline-none focus:ring-2 focus:ring-inset focus:ring-white" 
          @click="sidebarOpen = false"
        >
          <span class="sr-only">Close sidebar</span>
          <svg class="h-6 w-6 text-white" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Mobile Sidebar Nav Content -->
      <div class="flex-1 h-0 pt-5 pb-4 overflow-y-auto">
        <div class="flex-shrink-0 flex flex-col px-6">
          <span class="text-[28px] font-extrabold text-white tracking-tight leading-none lowercase">edify</span>
          <span class="text-[10px] font-bold text-[#8ba2b0] uppercase tracking-widest mt-1.5 leading-snug">Planning and monitoring<br>tool</span>
        </div>
        <nav class="mt-8 px-3 space-y-1">
          {% include "layouts/navigation_items.html" %}
        </nav>
      </div>
    </div>
  </div>

  <!-- Desktop Static Sidebar -->
  <aside class="hidden md:flex md:flex-shrink-0">
    <div class="flex flex-col w-[260px] bg-[#304654] border-r border-[#24333e] shadow-xl z-20">
      <div class="pt-8 pb-6 flex flex-col px-6">
        <span class="text-[32px] font-extrabold text-white tracking-tight leading-none lowercase">edify</span>
        <span class="text-[10.5px] font-semibold text-[#90a6b4] uppercase tracking-wider mt-2.5 leading-tight">Planning and monitoring<br>tool</span>
      </div>
      <div class="flex-1 flex flex-col min-h-0 overflow-y-auto overflow-x-hidden custom-scrollbar">
        <nav class="flex-1 px-4 pb-8 space-y-1">
          {% include "layouts/navigation_items.html" %}
        </nav>
      </div>
    </div>
  </aside>

  <!-- Main container -->
  <div class="flex-1 flex flex-col min-w-0 overflow-hidden">
    <!-- Topbar -->
    <header class="bg-white border-b border-[var(--border-card)] min-h-[64px] flex items-center justify-between px-4 sm:px-6 py-2 shrink-0 relative z-10 shadow-sm">
      <!-- Left: Mobile menu toggle + Page Title block -->
      <div class="flex items-center gap-4 flex-1 min-w-0">
        <button 
          type="button" 
          class="md:hidden h-9 w-9 flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 focus:outline-none shrink-0" 
          @click="sidebarOpen = true"
        >
          <span class="sr-only">Open sidebar</span>
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <div class="min-w-0 truncate">
          {% block topbar_left %}{% endblock %}
        </div>
      </div>

      <!-- Middle: Search and Global Filters -->
      <div class="hidden lg:flex items-center justify-center flex-1 px-4">
        {% block topbar_middle %}
          <!-- Default generic search if none provided -->
          <div class="relative w-full max-w-md">
            <svg class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input type="text" placeholder="Search..." class="w-full pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-[13px] focus:ring-2 focus:ring-[#304654] focus:border-transparent focus:outline-none transition-shadow" />
            <div class="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <kbd class="hidden sm:inline-block border border-slate-200 rounded px-1.5 text-[10px] font-bold text-slate-400 bg-white">⌘</kbd>
              <kbd class="hidden sm:inline-block border border-slate-200 rounded px-1.5 text-[10px] font-bold text-slate-400 bg-white">K</kbd>
            </div>
          </div>
        {% endblock %}
      </div>

      <!-- Right: Actions, Notifications, User -->
      <div class="flex items-center justify-end gap-3 flex-1 shrink-0">
        {% block topbar_right %}{% endblock %}

        <!-- System Health Link -->
        {% if request.user.active_role in 'Admin,CountryDirector,ImpactAssessment' %}
        <a 
          href="/system-health" 
          class="h-9 w-9 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-[#304654] flex items-center justify-center transition-colors relative"
          title="System Health"
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
          </svg>
        </a>
        {% endif %}

        <!-- Notifications Bell -->
        <button class="relative h-9 w-9 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-[#304654] flex items-center justify-center transition-colors">
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
          </svg>
          <span class="absolute top-1.5 right-1.5 block h-2 w-2 rounded-full bg-rose-500 ring-2 ring-white"></span>
        </button>

        <!-- Role Switcher (Multi-role support) -->
        {% if request.user.role_enums|length > 1 %}
        <div class="relative" x-data="{ open: false }">
          <button 
            @click="open = !open" 
            class="h-9 flex items-center gap-2 pl-2 pr-1 rounded-lg hover:bg-slate-50 transition-colors focus:outline-none"
          >
            <div class="h-7 w-7 rounded-full bg-slate-100 text-[#304654] font-bold text-[11px] grid place-items-center uppercase shadow-inner shrink-0">
              {{ request.user.name|slice:":2" }}
            </div>
            <div class="hidden sm:block text-left min-w-0">
              <p class="text-[12px] font-extrabold text-slate-800 truncate leading-tight">{{ request.user.name }}</p>
              <p class="text-[10px] text-slate-500 font-semibold truncate leading-tight">{{ request.user.active_role }}</p>
            </div>
            <svg class="h-4 w-4 text-slate-400 shrink-0" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd" /></svg>
          </button>
          <div 
            x-show="open" 
            @click.outside="open = false" 
            class="absolute right-0 mt-2 w-56 bg-white border border-slate-200 rounded-xl shadow-lg py-1 text-[12px] z-50 overflow-hidden"
            style="display: none;"
          >
            <div class="px-4 py-2 border-b border-slate-100 bg-slate-50">
              <p class="text-[10px] uppercase font-bold text-slate-400 tracking-wider">Switch Role</p>
            </div>
            <div class="max-h-[300px] overflow-y-auto">
              {% for r in request.user.role_enums %}
                <form action="/auth/switch-role" method="post" class="m-0">
                  {% csrf_token %}
                  <input type="hidden" name="role" value="{{ r.value }}">
                  <button 
                    type="submit" 
                    class="w-full text-left px-4 py-2.5 hover:bg-slate-50 flex items-center justify-between group transition-colors"
                  >
                    <span class="font-semibold {% if request.user.active_role == r.value %}text-[#304654] font-bold{% else %}text-slate-600 group-hover:text-slate-900{% endif %}">
                      {{ r.value }}
                    </span>
                    {% if request.user.active_role == r.value %}
                    <svg class="h-4 w-4 text-[#304654]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                    {% endif %}
                  </button>
                </form>
              {% endfor %}
            </div>
            <div class="border-t border-slate-100 mt-1">
              <form action="/logout" method="post" class="m-0">
                {% csrf_token %}
                <button type="submit" class="w-full text-left px-4 py-2.5 text-rose-600 hover:bg-rose-50 font-bold transition-colors">
                  Sign out
                </button>
              </form>
            </div>
          </div>
        </div>
        {% else %}
        <div class="h-9 flex items-center gap-2 pl-2 pr-3">
          <div class="h-7 w-7 rounded-full bg-slate-100 text-[#304654] font-bold text-[11px] grid place-items-center uppercase shadow-inner shrink-0">
            {{ request.user.name|slice:":2" }}
          </div>
          <div class="hidden sm:block text-left min-w-0">
            <p class="text-[12px] font-extrabold text-slate-800 truncate leading-tight">{{ request.user.name }}</p>
            <p class="text-[10px] text-slate-500 font-semibold truncate leading-tight">{{ request.user.active_role }}</p>
          </div>
          <form action="/logout" method="post" class="m-0 ml-2">
            {% csrf_token %}
            <button type="submit" class="text-rose-500 hover:text-rose-700 focus:outline-none" title="Sign out">
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </form>
        </div>
        {% endif %}
      </div>
    </header>

    <!-- Main Content Area -->
    <main class="flex-1 overflow-y-auto focus:outline-none relative">
      {% block shell_content %}{% endblock %}
    </main>
  </div>
</div>

<style>
/* Custom scrollbar for sidebar */
.custom-scrollbar::-webkit-scrollbar {
  width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
{% endblock %}
"""

with open("/Users/omario/Developer/Edify Planning Tool/edify-api/templates/layouts/shell.html", "w") as f:
    f.write(shell_content)
