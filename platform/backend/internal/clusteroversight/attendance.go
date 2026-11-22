package clusteroversight

import "sort"

// session is one delivered meeting or group training with a register
// (profile_insights.SessionRow).
type session struct {
	id, name          string
	heldOn, fy, area  string
	isTraining        bool
	teachers, leaders int
	invited, attended map[string]bool
}

func (s session) rate() *int {
	if len(s.invited) == 0 {
		return nil
	}
	v := pyRoundInt(float64(100*min(len(s.attended), len(s.invited))) / float64(len(s.invited)))
	return &v
}

// schoolAttendance is a member school at its cluster's sessions
// (profile_insights.SchoolAttendanceRow).
type schoolAttendance struct {
	id, code, name    string
	invited, attended int
	lastAttended      string
	missedInARow      int
}

func (s schoolAttendance) rate() *int {
	if s.invited == 0 {
		return nil
	}
	v := pyRoundInt(float64(100*s.attended) / float64(s.invited))
	return &v
}

func (s schoolAttendance) isDrifting() bool {
	return s.missedInARow >= rules.MissedInARowAlert
}

// attendance is profile_insights._attendance_of for one cluster.
type attendance struct {
	schools      []schoolAttendance
	driftingRows []schoolAttendance
	// sessions are the year's, allSessions every year's, newest first.
	sessions, allSessions []session
	withoutRegister       int
	drifting, represented int
	invitedTotal          int
	attendedTotal         int
	// teachers and leaders are those recorded for the schools at the
	// year's sessions they attended.
	teachers, leaders int
	// rate is the year's attendance out of 100, nil with no invitation.
	rate *int
}

// attendanceOf reads one cluster's attendance from its member schools, its
// delivered sessions in the order they were read, and their register.
//
// Invited and attended count the sessions of fiscal year fy; "missed in a
// row" counts back from the latest session a school was invited to, across
// years. A delivered session nobody was ticked at has no register and
// counts against no school.
func attendanceOf(members []memberRow, sessions []sessionRow, register map[string]map[string]registerRow, fy string) attendance {
	type entry struct {
		heldOn   string
		attended bool
	}
	rows := make([]schoolAttendance, len(members))
	for i, m := range members {
		rows[i] = schoolAttendance{id: m.ID, code: m.Code, name: m.Name}
	}
	timeline := make([][]entry, len(members))
	out := attendance{}
	for _, activity := range sessions {
		came, asked := map[string]bool{}, map[string]bool{}
		for school, row := range register[activity.ID] {
			if row.Attended {
				came[school] = true
			}
			if row.Invited {
				asked[school] = true
			}
		}
		// The older record of who came, kept on the activity itself.
		for _, school := range activity.Attended {
			came[school] = true
		}
		if len(came) == 0 {
			out.withoutRegister++
			continue
		}
		for school := range came {
			asked[school] = true
		}
		name := activity.Name
		if name == "" {
			name = sessionDisplayName(activity.Type, "", "", false)
		}
		s := session{
			id: activity.ID, name: name,
			heldOn: activity.HeldOn, fy: activity.FY, area: activity.Focus,
			isTraining: in(rules.TrainingTypes, activity.Type), invited: asked, attended: came,
		}
		for school := range came {
			if row, ok := register[activity.ID][school]; ok {
				s.teachers += row.Teachers
				s.leaders += row.Leaders
			}
		}
		out.allSessions = append(out.allSessions, s)
		for i, m := range members {
			school := m.ID
			if !asked[school] {
				continue
			}
			timeline[i] = append(timeline[i], entry{s.heldOn, came[school]})
			if s.fy != fy {
				continue
			}
			rows[i].invited++
			if came[school] {
				rows[i].attended++
				if row, ok := register[activity.ID][school]; ok {
					out.teachers += row.Teachers
					out.leaders += row.Leaders
				}
			}
		}
	}
	for i := range rows {
		newestFirst := timeline[i]
		sort.SliceStable(newestFirst, func(a, b int) bool { return newestFirst[a].heldOn > newestFirst[b].heldOn })
		for _, e := range newestFirst {
			if e.attended {
				rows[i].lastAttended = e.heldOn
				break
			}
			rows[i].missedInARow++
		}
	}
	sort.SliceStable(out.allSessions, func(a, b int) bool { return out.allSessions[a].heldOn > out.allSessions[b].heldOn })
	for _, s := range out.allSessions {
		if s.fy == fy {
			out.sessions = append(out.sessions, s)
		}
	}
	for _, row := range rows {
		if row.isDrifting() {
			out.drifting++
			out.driftingRows = append(out.driftingRows, row)
		}
		if row.attended > 0 {
			out.represented++
		}
		out.invitedTotal += row.invited
		out.attendedTotal += row.attended
	}
	sort.SliceStable(out.driftingRows, func(a, b int) bool {
		if out.driftingRows[a].missedInARow != out.driftingRows[b].missedInARow {
			return out.driftingRows[a].missedInARow > out.driftingRows[b].missedInARow
		}
		return out.driftingRows[a].name < out.driftingRows[b].name
	})
	if out.invitedTotal > 0 {
		rate := pyRoundInt(float64(100*out.attendedTotal) / float64(out.invitedTotal))
		out.rate = &rate
	}
	out.schools = rows
	return out
}

// kindAttendance is scores._kind_attendance: (invitations kept, invitations)
// by member schools at the year's meetings, or at its group trainings.
func (a attendance) kindAttendance(members map[string]bool, trainings bool) (kept, asked int) {
	for _, s := range a.sessions {
		if s.isTraining != trainings {
			continue
		}
		for school := range s.invited {
			if members[school] {
				asked++
			}
		}
		for school := range s.attended {
			if members[school] {
				kept++
			}
		}
	}
	return kept, asked
}
