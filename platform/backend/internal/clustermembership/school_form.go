package clustermembership

import (
	"fmt"
	"sort"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// A school's own Add to Cluster drawer (school_views.add_to_cluster_flow as
// the feed reads it: mobile_feed cluster_form and cluster_choice).

// ownerCluster is one of the school owner's active clusters, marked as the
// flow marks it.
type ownerCluster struct {
	ID, Name, DistrictID, District string
	Schools                        int
	// Serves is a formal catchment of the school's district (a label);
	// Cross is a cluster in another district; Current is the school's own.
	Serves, Cross, Current bool
}

// schoolFacts is the school as the drawer reads it.
type schoolFacts struct {
	ID, Code, Name, DistrictID, District, SubCountyID, SubCounty, RegionID string
	ClusterID, ClusterStatus, AccountOwner                                 string
}

// formState is the rest of what the form says.
type formState struct {
	isChange, selectable             bool
	current, preselected, ineligible string
	errorText                        string
}

func clusterChoiceOf(c ownerCluster) *screensv1.ActionChoice {
	label := c.Name + " · " + c.District
	switch {
	case c.Current:
		label += " (current)"
	case c.Cross:
		label += " · Cross-District Cluster"
		if c.Serves {
			label += " (approved neighbouring district)"
		}
	}
	plural := "s"
	if c.Schools == 1 {
		plural = ""
	}
	label += fmt.Sprintf(" · %d school%s", c.Schools, plural)
	return &screensv1.ActionChoice{Value: c.ID, Label: label, Disabled: c.Current}
}

// sortOwnerClusters is the flow's sort: served first, the school's own
// district first among those, the current one last of its kind, by name.
func sortOwnerClusters(cs []ownerCluster) {
	key := func(b bool) int {
		if b {
			return 1
		}
		return 0
	}
	sort.SliceStable(cs, func(i, j int) bool {
		a, b := cs[i], cs[j]
		switch {
		case a.Serves != b.Serves:
			return a.Serves
		case a.Cross != b.Cross:
			return key(a.Cross) < key(b.Cross)
		case a.Current != b.Current:
			return key(a.Current) < key(b.Current)
		}
		return strings.ToLower(a.Name) < strings.ToLower(b.Name)
	})
}

func or(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

// schoolForm is mobile_feed.cluster_form.
func schoolForm(sc schoolFacts, ownerName string, clusters []ownerCluster, st formState) *screensv1.AddToClusterForm {
	notice := ""
	switch {
	case len(clusters) > 0:
		if !st.selectable {
			notice = "This school's owner has no active cluster to add it to."
		}
	case st.ineligible != "":
		notice = st.ineligible
	default:
		notice = or(ownerName, "This school's owner") + " has no active cluster yet — create one to add the school."
	}
	district := or(sc.District, "the school's district")
	subCounty := or(sc.SubCounty, "the district")
	place := sc.SubCounty
	if place == "" {
		place = district
	}
	f := &screensv1.AddToClusterForm{
		Title: "Add " + sc.Name + " to cluster", IsChange: st.isChange, CurrentClusterName: st.current,
		PreselectedClusterId: st.preselected, HasSelectableCluster: st.selectable, ClusterNotice: notice,
		NewClusterPlaceholder: "e.g. " + place + " Cluster",
		NewClusterNote:        "A new cluster is created in " + district + ", covering " + subCounty + ".",
		ReasonPlaceholder:     "Why this school joins a cluster across the district border",
		SubmitLabel:           "Add to cluster", Error: st.errorText,
	}
	if st.isChange {
		f.Title = "Change cluster for " + sc.Name
		f.ReasonPlaceholder = "Why this school moves to another cluster"
		f.ConfirmLabel = "Move this school out of " + or(st.current, "its current cluster") + "."
		f.SubmitLabel = "Change cluster"
	}
	if ownerName != "" {
		f.OwnerNote = "Clusters of " + ownerName + " (the school's owner)."
	}
	f.Clusters = []*screensv1.ActionChoice{}
	f.CrossDistrictClusterIds = []string{}
	for _, c := range clusters {
		f.Clusters = append(f.Clusters, clusterChoiceOf(c))
		if c.Cross {
			f.CrossDistrictClusterIds = append(f.CrossDistrictClusterIds, c.ID)
		}
	}
	return f
}
