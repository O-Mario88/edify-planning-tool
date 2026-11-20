package feeddom

import "testing"

// Two parts drawn as elements with nothing between them read apart, joined
// by " · ", as page_blocks.Node.text reads them (TitleAndLineTextTest).
func TestTwoPartsDrawnApartReadApart(t *testing.T) {
	cases := []struct {
		name string
		node *Node
		want string
	}{
		{"title and line", El("div", "", El("strong", "", "NSSF compliance"), El("span", "", "National Social Security Fund")), "NSSF compliance · National Social Security Fund"},
		{"label and figure", El("p", "", El("span", "", "Cluster Meetings"), El("span", "", "UGX 291K")), "Cluster Meetings · UGX 291K"},
		{"a figure and its unit", El("p", "", El("b", "", "3"), El("span", "", "schools")), "3schools"},
		{"spaced parts", El("p", "", El("span", "", "Kampala"), " ", El("span", "", "Central")), "Kampala Central"},
		{"running text", El("p", "", "Visits ", El("b", "", "Planned"), " this week"), "Visits Planned this week"},
		{"a sentence already ended", El("p", "", El("span", "", "Done."), El("span", "", "Next")), "Done.Next"},
		{"capitals on the left", El("p", "", El("span", "", "UGX"), El("span", "", "Budget")), "UGXBudget"},
	}
	for _, c := range cases {
		if got := c.node.Text(); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
	}
}

// JoinParts reads parts drawn side by side as Node.text reads the same
// elements: the Target Distribution's details, a fund legend's line.
func TestJoinPartsReadsAsTheElementsWouldRead(t *testing.T) {
	cases := []struct {
		parts []string
		want  string
	}{
		{[]string{"Cluster Meetings", "UGX 291K"}, "Cluster Meetings · UGX 291K"},
		{[]string{"Unit", "schools", "Portfolio"}, "Unitschools · Portfolio"},
		{[]string{"Unit", "", "Portfolio"}, "Unit · Portfolio"},
		{[]string{"Rescheduled 2 time(s)", "Mukono Primary"}, "Rescheduled 2 time(s)Mukono Primary"},
	}
	for _, c := range cases {
		if got := JoinParts(c.parts...); got != c.want {
			t.Errorf("%q: %q, want %q", c.parts, got, c.want)
		}
		el := El("div", "")
		for _, p := range c.parts {
			el.children = append(el.children, El("span", "", p))
		}
		if got := el.Text(); got != c.want {
			t.Errorf("%q as elements: %q, want %q", c.parts, got, c.want)
		}
	}
}
