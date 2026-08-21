from django.test import SimpleTestCase

from .test_design_system_quality import _read


def _regional_source():
    """Return component behavior and its shared stylesheet as one contract."""

    return "\n".join(
        (
            _read("templates/partials/analytics/regional_performance.html"),
            _read("static/css/components.css"),
        )
    )


class RegionalPerformanceTooltipTest(SimpleTestCase):
    def test_tooltip_starts_at_cursor_tail_and_only_flips_at_map_edges(self):
        template = _regional_source()

        self.assertIn('x-ref="tip"', template)
        self.assertIn("const edge = 4, cursorTail = 14;", template)
        self.assertIn("let x = px + cursorTail, y = py + cursorTail;", template)
        self.assertIn("x = px - width - cursorTail;", template)
        self.assertIn("y = py - height - cursorTail;", template)
        self.assertIn("const viewportWidth = window.innerWidth;", template)
        self.assertIn("const viewportHeight = window.innerHeight;", template)
        self.assertIn(
            "clientY + cursorTail + height > viewportHeight - edge",
            template,
        )
        self.assertIn(
            "this.$nextTick(() => this._placeTip(clientX, clientY));", template
        )
        self.assertNotIn("e.clientY - box.top - 40", template)

    def test_tooltip_width_cannot_overflow_a_narrow_map(self):
        template = _regional_source()

        self.assertIn("width:clamp(204px, 46%, 300px);", template)
        self.assertIn(
            "max-width:min(calc(100% - 8px), calc(100vw - 1rem));",
            template,
        )
        self.assertIn("padding:clamp(8px, 1.4vw, 14px);", template)
        self.assertIn(
            ".sr-tip__title,.sr-tip__primary{font-size:var(--edify-text-body-size)}",
            template,
        )
        self.assertNotIn("font-size:clamp(12px, 1.15vw, 15px)", template)

    def test_mobile_summary_metrics_share_one_compact_row(self):
        template = _regional_source()

        self.assertIn("sr-tip__top grid grid-cols-3", template)
        self.assertIn(".sr-tip__top{\n      display:flex;", template)
        self.assertIn("justify-content:space-between;", template)
        self.assertIn(".sr-tip__top > div{", template)
        self.assertIn("white-space:nowrap;", template)

        schools = "{ k:'Schools',  v: this._n(d.schools) }"
        core = "{ k:'Core',     v: this._n(d.core_schools) }"
        clusters = "{ k:'Clusters', v: this._n(d.clusters) }"
        first_summary = template.index(schools)
        self.assertLess(first_summary, template.index(core, first_summary))
        self.assertLess(
            template.index(core, first_summary),
            template.index(clusters, first_summary),
        )

    def test_boundary_hover_only_lifts_active_geography(self):
        template = _regional_source()

        self.assertIn("sr-boundary-layer sr-district-layer", template)
        self.assertIn("sr-boundary-layer sr-subcounty-layer", template)
        self.assertIn("promoteBoundary(el){", template)
        self.assertIn("releaseBoundary(el){", template)
        self.assertIn("const lift = el.cloneNode(false);", template)
        self.assertIn("lift.setAttribute('pointer-events', 'none');", template)
        self.assertIn("layer.appendChild(lift);", template)
        self.assertIn("document.addEventListener(\n          'pointermove'", template)
        self.assertIn("if(target !== active) this.releaseBoundary(active);", template)
        self.assertIn("transform:scale(1.05) !important;", template)
        self.assertIn("transform:scale(1.04) !important;", template)
        self.assertIn("#sr-cam .sr-boundary-layer > path.sr-boundary-lift{", template)
        self.assertIn("stroke:none;\n    stroke-width:0;", template)
        self.assertIn("drop-shadow(0 1px 1.5px rgba(15,23,42,.72))", template)
        self.assertIn("drop-shadow(0 9px 6px rgba(15,23,42,.36))", template)
        self.assertNotIn("drop-shadow(0 1px 0 rgba(255,255,255", template)
        self.assertIn("transform:none !important;", template)

        hover_css = template.split("#sr-cam .sr-boundary-layer > path{", 1)[1].split(
            "#sr-cam .sr-subcounty-layer path:focus-visible", 1
        )[0]
        self.assertNotIn("path:not(.sr-boundary-active)", hover_css)
        self.assertNotIn("opacity:.26", hover_css)
        self.assertNotIn("brightness(", hover_css)
        self.assertNotIn("saturate(", hover_css)
        self.assertNotIn("sr-context-active", template)

    def test_map_names_have_no_outline(self):
        template = _regional_source()

        self.assertIn("#sr-cam text{text-anchor:middle", template)
        self.assertIn("stroke:none;transition:opacity .3s", template)
        self.assertNotIn("paint-order:stroke fill;stroke:#fff", template)

    def test_map_renders_toggleable_school_distribution_pins(self):
        template = _regional_source()

        self.assertIn(
            'role="group" aria-labelledby="school-map-legend-title"', template
        )
        self.assertIn("toggleSchoolType(type.key)", template)
        # The pins read each district's own distribution through schoolMix().
        # This used to assert the literal line inside syncSchoolTotals, which
        # summed the cohorts across every district -- a country-wide figure
        # that moved to the server (§40 permits no authoritative business
        # analytic in JavaScript). That assertion pinned an implementation
        # detail of the legend, not the behaviour of the pins.
        self.assertIn("school_distribution", template)
        self.assertIn("schoolMix(district)", template)
        self.assertIn("class','sr-school-pin'", template)
        self.assertIn("appendPinVisual(pin, type", template)
        self.assertNotIn("sr-pin-count", template)
        self.assertNotIn("this.compact(mix[type.key])", template)

    def test_the_legend_totals_come_from_the_server(self):
        """Country-wide cohort counts are an authoritative figure, so they are
        computed in apps.analytics.country_map_context, not summed here."""
        template = _regional_source()

        self.assertIn("subregion-school-type-totals", template)
        self.assertNotIn("districts.reduce(", template)

    def test_school_legend_sits_below_the_map_without_outlined_pills(self):
        template = _regional_source()

        map_end = template.index("</svg>")
        legend_start = template.index('id="school-map-legend-title"')
        distribution_start = template.index("Distribution by ${distributionLevel()}")
        self.assertLess(map_end, legend_start)
        self.assertLess(legend_start, distribution_start)
        self.assertIn(
            'role="group" aria-labelledby="school-map-legend-title"', template
        )
        legend_controls = template[legend_start:distribution_start]
        self.assertIn("hover:bg-slate-50", legend_controls)
        self.assertNotIn("border border-slate-200 edify-surface", legend_controls)

    def test_country_totals_sit_below_the_distribution_heading(self):
        template = _regional_source()

        heading = template.index("Distribution by ${distributionLevel()}")
        districts = template.index(
            "{{ subregion_performance.totals.districts }} districts", heading
        )
        subregions = template.index(
            "{{ subregion_performance.totals.subregions }} sub-regions", districts
        )
        schools = template.index(
            "{{ subregion_performance.totals.schools }} schools", subregions
        )
        table = template.index(
            '<table class="sr-distribution-table w-full text-left text-table-cell"'
        )
        self.assertLess(heading, districts)
        self.assertLess(districts, subregions)
        self.assertLess(subregions, schools)
        self.assertLess(schools, table)

    def test_school_pin_colours_match_the_classification_legend(self):
        template = _regional_source()

        self.assertIn(
            "{key:'core', label:'Core', colour:token('--edify-chart-orange')",
            template,
        )
        self.assertIn(
            "{key:'client', label:'Client', colour:token('--edify-chart-blue')",
            template,
        )
        self.assertIn(
            "{key:'champion', label:'Champion', colour:token('--edify-chart-green')",
            template,
        )
        self.assertIn(
            "{key:'core_trained', label:'Core trained', "
            "colour:token('--edify-warning-text')",
            template,
        )
        self.assertIn("class', 'sr-pin-check'", template)

    def test_subcounty_markers_do_not_obscure_place_names(self):
        template = _regional_source()

        self.assertIn(
            "M0,0 C-.9,-2.1 -4.5,-4.5 -4.5,-7.5 A4.5,4.5",
            template,
        )
        self.assertIn("* 7;", template)
        self.assertIn(
            "font-size:var(--edify-svg-text-micro,var(--edify-text-micro-size));",
            template,
        )
        self.assertIn("font-weight:var(--edify-text-label-weight)", template)
        self.assertIn("stroke:none;transition:opacity .3s", template)
        self.assertNotIn("stroke-width:1.4px", template)
        self.assertLess(
            template.index("this.cam.insertBefore(pinLayer, this.labels);"),
            template.index("this.cam.insertBefore(labelLayer, this.labels);"),
        )

    def test_district_and_subcounty_labels_stay_on_their_boundaries(self):
        template = _regional_source()

        self.assertIn("placeBoundaryLabels({", template)
        self.assertIn(
            "labelLayer, pathLayer, pinLayer, key, scale=1,",
            template,
        )
        self.assertIn("placeDistrictLabels(){", template)
        self.assertIn("resolveSubcountyLabelCollisions(){", template)
        self.assertIn(
            "[6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72].forEach",
            template,
        )
        self.assertIn("for(let step = 0; step < 16; step += 1)", template)
        self.assertIn("markerObstacleRects(layer, scale)", template)
        self.assertIn("boundaryContainsLabel(path, rect)", template)
        self.assertIn("boundaryContainsPoint(path, x, y)", template)
        self.assertIn("path.isPointInFill(point)", template)
        self.assertIn("const overlaps = (a, b) =>", template)
        self.assertIn(
            "placed.every(existing => !overlaps(rect, existing)) &&", template
        )
        self.assertIn("markerRects.every(marker => !overlaps(rect, marker))", template)
        self.assertIn("labelScales=[1], allowOverlapFallback=false,", template)
        self.assertIn("labelScales:[1, 0.9, 0.82],", template)
        self.assertIn("allowOverlapFallback:true,", template)
        self.assertIn("label.dataset.labelPlacement = 'hidden';", template)
        self.assertIn("label.style.opacity = 0;", template)
        self.assertIn("placement = 'boundary-fit';", template)
        self.assertIn(
            "placement = anchor.fullFit ? 'boundary-fit' : 'boundary-anchor';", template
        )
        self.assertNotIn("placement = 'open-space';", template)
        self.assertIn("const blocked =", template)
        self.assertIn("placed.some(existing => overlaps(rect, existing))", template)
        self.assertIn("dataset.mapAnchorX", template)
        self.assertIn("dataset.mapAnchorY", template)
        self.assertIn("dataset.pinCount", template)
        self.assertIn("label.dataset.labelX", template)
        self.assertIn("label.dataset.labelY", template)
        self.assertIn("label.dataset.labelPriority", template)
        self.assertIn("label.dataset.labelOffset =", template)
        self.assertIn("label.dataset.labelScale =", template)
        self.assertIn("label.dataset.labelPlacement = placement;", template)
        self.assertIn("this.placeDistrictLabels();", template)
        self.assertIn("this.resolveSubcountyLabelCollisions();", template)
        self.assertIn(
            "requestAnimationFrame(() => this.resolveSubcountyLabelCollisions());",
            template,
        )
        self.assertNotIn("declash(){", template)

    def test_subcounty_labels_are_complete_and_use_compact_title_case(self):
        template = _regional_source()

        self.assertIn("label.textContent = properties.n;", template)
        self.assertNotIn("label.textContent = properties.n.toUpperCase();", template)
        self.assertIn(
            "placement = anchor.fullFit ? 'boundary-fit' : 'boundary-anchor';", template
        )

    def test_national_overview_keeps_every_district_label_visible(self):
        template = _regional_source()

        self.assertIn("labelScales:[0.82, 0.74, 0.68],", template)
        self.assertIn("allowOverlapFallback:true,", template)
        self.assertIn("}else if(allowOverlapFallback){", template)
        self.assertNotIn("anchor-overlap", template)
        self.assertNotIn("density-hidden", template)
        self.assertNotIn("overviewDistrictLabelBudget", template)
        self.assertNotIn("visibleCount", template)
        self.assertIn("pathAreaByName", template)
        self.assertIn("t.textContent = p.d;", template)
        self.assertNotIn("t.textContent = p.d.toUpperCase();", template)

    def test_map_text_stays_on_the_shared_screen_type_scale(self):
        template = _regional_source()

        self.assertIn("data-edify-svg-typography", template)
        self.assertIn('@edify-svg-typography="refreshMapLabelPlacement()"', template)
        self.assertIn("refreshMapLabelPlacement(){", template)
        self.assertIn("if(this.subcountyLabelLayer)", template)
        self.assertIn("this.resolveSubcountyLabelCollisions();", template)
        self.assertIn("else if(!this.focused) this.placeDistrictLabels();", template)
        self.assertIn(
            "font-size:var(--edify-svg-text-micro,var(--edify-text-micro-size))",
            template,
        )
        self.assertIn("stroke-width:.16em", template)
        self.assertNotIn("stroke-width:2.2px", template)

    def test_subcounty_markers_refresh_after_school_geography_changes(self):
        template = _regional_source()

        self.assertIn('{{ map_scope|json_script:"subregion-map-scope" }}', template)
        self.assertIn("async refreshSubcountyMetrics(district){", template)
        self.assertIn("/api/analytics/map-subcounties?", template)
        self.assertIn("{cache:'no-store'}", template)
        self.assertIn("await this.refreshSubcountyMetrics(district);", template)
        self.assertIn("document.addEventListener('visibilitychange'", template)
        self.assertIn("delete this.combinedDistrictRequests[districtKey];", template)

    def test_distribution_table_tracks_the_active_map_level(self):
        template = _regional_source()

        self.assertIn("distributionLevel(){", template)
        self.assertIn("distributionRows(){", template)
        self.assertIn("focusDistributionRow(row){", template)
        self.assertIn("Distribution by ${distributionLevel()}", template)
        self.assertIn("row.level === 'subregion'", template)
        self.assertIn("row.level === 'district'", template)
        self.assertIn("level:'subcounty'", template)
        self.assertIn("this.subcountyDistributionRows = boundaryRows.sort(", template)
        self.assertIn("this.districtParentSubregion = parentSubregion;", template)
        self.assertIn("if(parentSubregion) this.focusSub(parentSubregion);", template)

    def test_zoom_does_not_magnify_the_district_focus_stroke(self):
        template = _regional_source()

        self.assertIn('x-ref="mapBack"', template)
        self.assertIn(
            "el.setAttribute('vector-effect', 'non-scaling-stroke');",
            template,
        )
        self.assertIn("this.cam.classList.add('sr-zoomed');", template)
        self.assertIn("this.cam.classList.remove('sr-zoomed');", template)
        self.assertIn(
            "this.$refs.mapBack?.focus({preventScroll:true})",
            template,
        )
        self.assertIn(
            "#sr-cam.sr-zoomed > g:first-child path:focus-visible",
            template,
        )

    def test_map_discloses_its_shared_country_scope(self):
        template = _regional_source()

        self.assertIn("Country-wide system data", template)
        self.assertIn("identical for every authorized analytics role", template)

    def test_subcounty_boundaries_are_lazy_loaded_only_after_district_zoom(self):
        template = _regional_source()
        zoom = template.split("zoom(el){", 1)[1].split("reset(){", 1)[0]

        self.assertIn("uganda_subcounty_index.json", template)
        self.assertIn("loadSubcounties(el.dataset.district);", zoom)
        self.assertIn("\"{% static 'geo/' %}\" + entry.file", template)
        self.assertIn("detailRequest", template)
        self.assertIn("subcountyCache", template)

    def test_subcounty_boundaries_support_second_level_zoom_and_step_back(self):
        template = _regional_source()

        self.assertIn("Click a sub-county to zoom further", template)
        self.assertIn("this.zoomSubcounty(path);", template)
        self.assertIn("zoomSubcounty(el){", template)
        self.assertIn("districtCamera:null", template)
        self.assertIn("this.districtCamera = {scale:s, tx, ty};", template)
        self.assertIn("this.scaleSubcountyOverlays(scale, name);", template)
        self.assertIn("this.focused = `subcounty:${name}`;", template)
        self.assertIn("back(){", template)
        self.assertIn("this.focused = this.focusedDistrict;", template)
        self.assertIn('@keydown.escape.window="back()"', template)
        self.assertIn("cursor:zoom-in", template)

    def test_subcounty_metric_refresh_does_not_recursively_request_itself(self):
        template = _regional_source()

        self.assertIn("combinedDistrictRequests:{}", template)
        self.assertIn(
            "if(!this.combinedDistrictRequests[districtRequestKey])", template
        )
        self.assertIn(
            "this.combinedDistrictRequests[districtRequestKey] = true;", template
        )
        self.assertNotIn("this._combineRequested = false;", template)

    def test_zoomed_hover_card_switches_to_subcounty_metrics(self):
        template = _regional_source()

        self.assertIn(
            '{{ subcounty_insight|json_script:"subregion-subcounty-metrics" }}',
            template,
        )
        self.assertIn("this.tip.level = 'Sub-county';", template)
        self.assertIn("this._fillSubcounty(el);", template)
        self.assertIn("hoverSubcounty(path, event)", template)
        self.assertIn("SSA done", template)
        self.assertIn("Teachers", template)
        self.assertIn("Leaders", template)

    def test_ambiguous_or_missing_geography_is_disclosed_not_duplicated(self):
        template = _regional_source()

        self.assertIn("if(candidates.length !== 1)", template)
        self.assertIn("unmatched.push(metric);", template)
        self.assertIn("schools need'} sub-county mapping", template)
        self.assertIn("Needs sub-county mapping", template)

    def test_subcounty_drilldown_uses_saved_geography_not_point_in_polygon(self):
        template = _regional_source()

        self.assertIn("metric.subcounty", template)
        self.assertIn("metric.boundary_code", template)
        self.assertNotIn("pointInPolygon", template)
        self.assertNotIn("containsPoint", template)
