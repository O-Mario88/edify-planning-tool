package screens

import (
	"context"
	"testing"
)

func TestADrawerPathMayNameARecordsStep(t *testing.T) {
	ok := []string{
		"/ia/framework/area/cmwabc123/submit",
		"/ia/framework/indicator/cmwabc123/review",
		"/cce-leadership/engagements/cmwabc123/share",
		"/staff-activity/follow-ups/cmwabc123/acknowledge",
		"/team/coaching/new?kind=field_observation",
	}
	for _, path := range ok {
		if _, err := drawerPath(context.Background(), path); err != nil {
			t.Errorf("%s refused: %v", path, err)
		}
	}
	refused := []string{
		"https://elsewhere.example/x",
		"/a/b/c/d/e/f/g",
		"/ia/../framework",
		"/ia/Framework",
		"//host/path",
	}
	for _, path := range refused {
		if _, err := drawerPath(context.Background(), path); err == nil {
			t.Errorf("%s accepted", path)
		}
	}
}
