package mscs

import (
	"testing"
	"time"
)

func TestReadStoryIsTheViewsReads(t *testing.T) {
	st, refusal := readStory(map[string]string{"title": " A change ", "narrative": " It grew. ", "story_date": " 2026-11-20 ", "school_id": " 1442 "})
	if refusal != "" || st.Title != "A change" || st.Narrative != "It grew." || st.School != "1442" ||
		!st.Date.Equal(time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("story = %+v, refusal %q", st, refusal)
	}
	for _, v := range []map[string]string{
		{"narrative": "x", "story_date": "2026-11-20"},
		{"title": "x", "story_date": "2026-11-20"},
		{"title": "x", "narrative": "y"},
	} {
		if _, refusal := readStory(v); refusal != "Title, story date and narrative are required." {
			t.Errorf("readStory(%v) refusal = %q", v, refusal)
		}
	}
	if _, refusal := readStory(map[string]string{"title": "x", "narrative": "y", "story_date": "20/11/2026"}); refusal != badDate {
		t.Errorf("an unreadable date = %q", refusal)
	}
}
