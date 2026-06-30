import re

nav_items = [
    # --- MY WORK ---
    ("MY WORK", None, None),
    ("Dashboard", "/dashboard", "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z", None),
    ("Planning", "/planning", "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01", "request.user.active_role in 'CCEO,CountryProgramLead,CountryDirector,ProjectCoordinator'"),
    ("My Plan", "/my-plan", "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z", "request.user.active_role in 'CCEO,CountryProgramLead,PartnerFieldOfficer'"),
    ("Daily Debrief", "/debriefs", "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", None),

    # --- SCHOOLS ---
    ("SCHOOLS", None, None),
    ("Schools", "/schools", "M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4", None),
    ("Clusters", "/clusters", "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z", None),
    ("Partners", "/partners", "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z", "request.user.active_role in 'CountryDirector,CountryProgramLead,Admin,PartnerFieldOfficer'"),

    # --- ACTIVITY ---
    ("ACTIVITY", None, None),
    ("Evidence", "/evidence", "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z", "request.user.active_role in 'CCEO,ImpactAssessment,CountryProgramLead'"),
    ("Fund Requests", "/fund-requests/weekly", "M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z", "request.user.active_role in 'ProgramAccountant,CCEO,CountryProgramLead,CountryDirector'"),
    ("My Budget", "/budgets/monthly", "M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z", "request.user.active_role in 'ProgramAccountant,CountryProgramLead,CountryDirector'"),
    ("Completed Activities", "/trainings", "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01", "request.user.active_role in 'CCEO,CountryProgramLead,CountryDirector'"),

    # --- INSIGHTS ---
    ("INSIGHTS", None, None),
    ("Analytics", "/analytics", "M11 3.055A9.001 9.001 0 1020.945 13H11V3.055z", None),
    ("Reports", "/reports", "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z", None),

    # --- ACCOUNT ---
    ("ACCOUNT", None, None),
    ("Messages", "/messages", "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z", None),
    ("Notifications", "/notifications", "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9", None),

    # --- MORE TOOLS ---
    ("MORE TOOLS", None, None),
    ("Visits", "/visits", "M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6", "request.user.active_role in 'CCEO,CountryProgramLead,CountryDirector'"),
    ("My Team", "/my-team", "M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z", "request.user.active_role == 'CountryProgramLead'"),
    ("Core Schools", "/core-schools", "M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z", None),
    ("Projects", "/projects", "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z", None),
    ("Admin Panel", "/admin-panel", "M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4", "request.user.active_role in 'Admin,CountryDirector'"),
]

output = []

for item in nav_items:
    if item[1] is None:
        header = f"""
<!-- {item[0]} -->
<p class="px-2 pt-6 pb-2 text-[10.5px] font-bold text-[#748e9c] uppercase tracking-widest">{item[0]}</p>
"""
        output.append(header)
    else:
        name, path, path_d, condition = item
        
        # Determine exact match condition if it's dashboard, else prefix match
        if path == "/dashboard":
            active_cond = f"request.path == '{path}'"
        else:
            active_cond = f"'{path}' in request.path"

        html = f"""
<a 
  href="{path}" 
  class="group flex items-center gap-3 pr-3 pl-2 py-2 text-[13px] rounded-xl transition-all border {{% if {active_cond} %}}bg-[#3f5462] border-[#506674] text-white shadow-sm shadow-[#1a252f] border-l-[3px] border-l-amber-500{{% else %}}border-transparent text-[#90a6b4] hover:bg-[#3f5462]/50 hover:text-white{{% endif %}}"
>
  <div class="h-8 w-8 rounded-lg flex items-center justify-center shrink-0 transition-colors {{% if {active_cond} %}}bg-amber-500/20 text-amber-500{{% else %}}bg-white/[0.04] text-[#90a6b4] group-hover:text-white group-hover:bg-white/[0.08]{{% endif %}}">
    <svg class="h-4.5 w-4.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="{path_d}" />
    </svg>
  </div>
  <span class="{{% if {active_cond} %}}font-semibold{{% else %}}font-medium{{% endif %}}">{name}</span>
</a>
"""
        if condition:
            output.append(f"{{% if {condition} %}}\n{html.strip()}\n{{% endif %}}")
        else:
            output.append(html.strip())

with open("/Users/omario/Developer/Edify Planning Tool/edify-api/templates/layouts/navigation_items.html", "w") as f:
    f.write("\n\n".join(output))

