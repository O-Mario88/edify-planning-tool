from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from apps.core.permissions import require_page_permission
from apps.schools.models import SSAImportBatch
from apps.ssa.models import SsaRecord
from apps.ssa.upload_service import upload_ssa_file, import_ssa_batch
from apps.core.enums import VerificationStatus
from django.utils import timezone

@require_page_permission("ssa")
def ssa_upload_center_view(request):
    if request.method == "POST":
        file = request.FILES.get("file")
        if not file:
            messages.error(request, "A file is required for upload.")
            return redirect("/ssa/upload/")
        
        try:
            result = upload_ssa_file(file, request.user)
            # Find the newly created batch
            batch = SSAImportBatch.objects.filter(uploaded_by=request.user.user_id).order_by("-created_at").first()
            if batch:
                return redirect(f"/ssa/upload/{batch.id}/preview/")
            else:
                messages.error(request, result.get("message", "Error uploading file."))
        except Exception as e:
            messages.error(request, f"Upload error: {e}")
            
    return render(request, "pages/ssa/upload_center.html")

@require_page_permission("ssa")
def ssa_upload_preview_view(request, batch_id):
    batch = get_object_or_404(SSAImportBatch, id=batch_id)
    rows = batch.rows.all()
    
    if request.method == "POST":
        result = import_ssa_batch(batch, request.user)
        messages.success(request, f"Import finalized: {result['created']} records verified, {result['unmatched']} unmatched rows queued.")
        return redirect(f"/ssa/upload/{batch.id}/result/")
        
    ready_rows = rows.filter(status="ready")
    unmatched_rows = rows.filter(status="unmatched")
    blocked_rows = rows.filter(status="blocked")
    
    ready_count = ready_rows.count()
    unmatched_count = unmatched_rows.count()
    blocked_count = blocked_rows.count()
    
    context = {
        "batch": batch,
        "ready_rows": ready_rows,
        "unmatched_rows": unmatched_rows,
        "blocked_rows": blocked_rows,
        "ready_count": ready_count,
        "unmatched_count": unmatched_count,
        "blocked_count": blocked_count,
        "total_count": ready_count + unmatched_count + blocked_count,
    }
    return render(request, "pages/ssa/upload_preview.html", context)

@require_page_permission("ssa")
def ssa_upload_result_view(request, batch_id):
    batch = get_object_or_404(SSAImportBatch, id=batch_id)
    rows = batch.rows.all()
    
    context = {
        "batch": batch,
        "processed": rows.count(),
        "created": rows.filter(status="ready").count(),
        "unmatched": rows.filter(status="unmatched").count(),
        "failed": rows.filter(status="blocked").count(),
        "pending_verification": rows.filter(status="ready").count(), # since they land as pending
    }
    return render(request, "pages/ssa/upload_result.html", context)

@require_page_permission("ssa")
def ssa_verification_queue_view(request):
    records = SsaRecord.objects.filter(
        deleted_at__isnull=True,
        verification_status=VerificationStatus.PENDING.value
    ).select_related("school").order_by("-date_of_ssa")
    
    if request.method == "POST":
        record_id = request.POST.get("record_id")
        action = request.POST.get("action")
        rec = get_object_or_404(SsaRecord, id=record_id)
        
        if action == "verify":
            rec.verification_status = VerificationStatus.CONFIRMED.value
            rec.verified_by_user_id = request.user.user_id
            rec.verified_at = timezone.now()
            rec.save()
            
            # Update school status
            from apps.ssa.services import _recompute_readiness
            _recompute_readiness(rec.school)
            
            messages.success(request, f"SSA for '{rec.school.name}' has been successfully verified.")
        elif action == "return":
            rec.verification_status = VerificationStatus.RETURNED.value
            rec.save()
            
            from apps.ssa.services import _recompute_readiness
            _recompute_readiness(rec.school)
            
            messages.warning(request, f"SSA for '{rec.school.name}' returned for correction.")
            
        return redirect("/ssa/verification/")
        
    context = {
        "records": records,
        "total_pending": records.count(),
    }
    return render(request, "pages/ssa/verification_queue.html", context)
