"""Training ceilings — how many schools may be scheduled for a training.

``TrainingCeiling`` is one team member's, set by their Programme Lead.
``TrainingCountryCeiling`` is the country's, set by Admin or Impact
Assessment (owner, 2026-10-06: "The admin IA will set the Country Ceiling and
Leads will set each staff ceiling").


Owner, 2026-10-06: a Programme Lead sets, for each officer they supervise and
each training in the Training Catalogue, the most schools that officer may
schedule for it in a fiscal year. It is a ceiling on scheduling, never an
allocation: nothing is handed to the officer by setting it, and "Allocated"
keeps its existing meaning (a school assigned to a partner or to a project).

What is scheduled under it is never stored here. It is counted from the
persisted plans — the schools invited to the officer's group trainings and the
schools of their in-school trainings — in ``apps.planning.training_ceilings``,
the one place that does that sum and holds the line against it.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class TrainingCeiling(TimeStampedModel):
    id = CuidField()
    staff = models.ForeignKey(
        "accounts.StaffProfile",
        on_delete=models.CASCADE,
        related_name="training_ceilings",
    )
    training = models.ForeignKey(
        "activity_catalogue.ActivityCatalogueItem",
        on_delete=models.PROTECT,
        related_name="training_ceilings",
    )
    #: The operational fiscal year the ceiling applies to (apps.core.fy).
    fy = models.CharField(max_length=16)
    #: The most schools this staff member may schedule for this training in
    #: the year, group and in-school deliveries together.
    ceiling = models.PositiveIntegerField()
    set_by = models.CharField(max_length=30, blank=True, default="")
    set_by_role = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "training_ceiling"
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "training", "fy"],
                name="uniq_training_ceiling_staff_training_fy",
            ),
            models.CheckConstraint(
                condition=models.Q(ceiling__gte=1),
                name="training_ceiling_at_least_one",
            ),
        ]
        indexes = [models.Index(fields=["fy", "staff"])]

    def __str__(self) -> str:
        return f"{self.staff_id} · {self.training_id} · FY{self.fy}: {self.ceiling}"


class TrainingCountryCeiling(TimeStampedModel):
    """The most schools the country plans for one training in a fiscal year.

    Owner, 2026-10-06: "The admin IA will set the Country Ceiling ... The
    country ceiling will have Country Ceiling column, Planned column,
    Remaining column". Planned and Remaining are never stored: they are
    counted from the plans (``apps.planning.training_ceilings``).
    """

    id = CuidField()
    training = models.ForeignKey(
        "activity_catalogue.ActivityCatalogueItem",
        on_delete=models.PROTECT,
        related_name="country_training_ceilings",
    )
    #: The operational fiscal year the ceiling applies to (apps.core.fy).
    fy = models.CharField(max_length=16)
    #: The country it is set for, as staff profiles name it.
    country = models.CharField(max_length=64, blank=True, default="")
    ceiling = models.PositiveIntegerField()
    set_by = models.CharField(max_length=30, blank=True, default="")
    set_by_role = models.CharField(max_length=64, blank=True, default="")
    note = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        db_table = "training_country_ceiling"
        constraints = [
            models.UniqueConstraint(
                fields=["training", "fy", "country"],
                name="uniq_training_country_ceiling",
            ),
            models.CheckConstraint(
                condition=models.Q(ceiling__gte=1),
                name="training_country_ceiling_at_least_one",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.country} · {self.training_id} · FY{self.fy}: {self.ceiling}"


__all__ = ["TrainingCeiling", "TrainingCountryCeiling"]
