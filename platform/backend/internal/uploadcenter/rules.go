// Package uploadcenter builds the Upload Center (/uploads): the upload
// actions a role may start, the strip of what awaits review, is published
// and is overdue, the tabs, the table of the governed uploads the reader is
// authorised to see (school and SSA import batches, policies, manuals and
// training resources) and, for the Admin, the upload drawer's cards
// (apps.documents.views.upload_center_view, apps.documents.upload_center
// .UploadCenterService and pages/documents/upload_center.html, as the
// existing feed reads them).
//
// It reads; it never writes. It hands the page on for a query it does not
// know, more uploads than one page holds, a role without upload actions,
// and a document the reader does not administer whose audience names a
// partner or a project (the reader's partners and projects are not read
// here).
//
// The doors, actions, permissions and words are exported to rules.json by
// `manage.py export_upload_center_rules`; apps/documents/
// test_upload_center_rules_export.py fails when the two differ.
package uploadcenter

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Action is one upload a role may start.
type Action struct {
	Key           string `json:"key"`
	Category      string `json:"category"`
	Title         string `json:"title"`
	Description   string `json:"description"`
	Href          string `json:"href"`
	ActionLabel   string `json:"action_label"`
	TemplateHref  string `json:"template_href"`
	TemplateLabel string `json:"template_label"`
}

// Role is what a role is given on the page.
type Role struct {
	Page                   bool     `json:"page"`
	Actions                []Action `json:"actions"`
	AdminMenu              bool     `json:"admin_menu"`
	SchoolUpload           bool     `json:"school_upload"`
	SSAUpload              bool     `json:"ssa_upload"`
	DocumentsCreate        bool     `json:"documents_create"`
	TrainingCreate         bool     `json:"training_create"`
	ManageAcknowledgements bool     `json:"manage_acknowledgements"`
	Slug                   string   `json:"slug"`
	// NewPage opens New Policy or Manual.
	NewPage bool `json:"new_page"`
}

var rules = func() (r struct {
	Roles        map[string]Role   `json:"roles"`
	MetricLabels []string          `json:"metric_labels"`
	TypeLabels   map[string]string `json:"type_labels"`
	// NewDocumentTypes are New Policy or Manual's document types in order,
	// RoleChoices the roles it may be addressed to.
	NewDocumentTypes      [][2]string       `json:"new_document_types"`
	NewTrainingTypes      [][2]string       `json:"new_training_types"`
	RoleChoices           []string          `json:"role_choices"`
	DocumentStatuses      map[string]string `json:"document_statuses"`
	PreviewStatuses       map[string]string `json:"preview_statuses"`
	SchoolImportStatuses  map[string]string `json:"school_import_statuses"`
	SSAImportStatuses     map[string]string `json:"ssa_import_statuses"`
	TrainingTypes         []string          `json:"training_types"`
	PageSize              int               `json:"page_size"`
	AcknowledgementStates map[string]string `json:"acknowledgement_states"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("uploadcenter: reading rules.json: %v", err))
	}
	if len(r.MetricLabels) != 3 || r.PageSize <= 0 {
		panic("uploadcenter: rules.json lacks the figures' labels or the page size")
	}
	return r
}()

// label is a choice's name, or the stored value when it is no choice
// (get_FOO_display).
func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}
